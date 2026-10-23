import logging
from typing import cast
from uuid import uuid4

from celery import Task
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.api.serializers import (
    ConversationSerializer,
    RunCreateSerializer,
    TranscribeSerializer,
)
from apps.agents.api.sse import event_stream
from apps.agents.api.throttles import RunRateThrottle, TranscribeRateThrottle
from apps.agents.history import load_messages
from apps.agents.llm import DEFAULT_MODEL, DEFAULT_THINKING, MODELS, THINKING_LEVELS
from apps.agents.models import Conversation
from apps.agents.speech import TranscriptionError, transcribe
from apps.agents.tasks import run_agent

logger = logging.getLogger(__name__)


class ModelListView(APIView):
    @extend_schema(
        summary="Available models and reasoning levels",
        responses=inline_serializer(
            "ModelList",
            {
                "models": serializers.ListField(child=serializers.DictField()),
                "default_model": serializers.CharField(),
                "thinking_levels": serializers.ListField(child=serializers.CharField()),
                "default_thinking": serializers.CharField(),
            },
        ),
    )
    def get(self, request):
        return Response(
            {
                "models": [{"key": key, "label": m["label"]} for key, m in MODELS.items()],
                "default_model": DEFAULT_MODEL,
                "thinking_levels": THINKING_LEVELS,
                "default_thinking": DEFAULT_THINKING,
            }
        )


class RunCreateView(APIView):
    throttle_classes = [RunRateThrottle]

    @extend_schema(
        summary="Send a message (starts a run)",
        description="Answers right away. Read the answer from `stream_url` as Server-Sent Events.",
        request=RunCreateSerializer,
        responses={
            202: inline_serializer(
                "RunCreated",
                {
                    "run_id": serializers.CharField(),
                    "thread_id": serializers.CharField(),
                    "stream_url": serializers.CharField(),
                },
            )
        },
    )
    def post(self, request):
        serializer = RunCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = cast(dict, serializer.validated_data)  # DRF has no type hints

        run_id = uuid4().hex
        thread_id = data.get("thread_id") or uuid4().hex  # no thread_id: a new conversation
        Conversation.record_message(thread_id, data["message"])

        cast(Task, run_agent).delay(
            run_id=run_id,
            thread_id=thread_id,
            message=data["message"],
            lat=data.get("lat"),
            lon=data.get("lon"),
            model_key=data["model"],
            thinking=data["thinking"],
        )

        return Response(
            {
                "run_id": run_id,
                "thread_id": thread_id,
                "stream_url": reverse("agents:run-stream", args=[run_id]),
            },
            status=status.HTTP_202_ACCEPTED,
        )


class RunStreamView(View):
    """
    The run's events as Server-Sent Events.

    A plain Django view on purpose: DRF negotiates JSON-style responses and would answer the
    browser's `Accept: text/event-stream` with 406 Not Acceptable.

    Resumes after the last event the browser saw: EventSource sends it as the Last-Event-ID
    header when it reconnects, and the UI can pass it as ?after= after a page refresh.
    """

    def get(self, request, run_id: str):
        after = request.headers.get("Last-Event-ID") or request.GET.get("after") or "0"
        response = StreamingHttpResponse(
            event_stream(run_id, after), content_type="text/event-stream"
        )
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"  # tells nginx not to buffer this response
        return response


class ConversationListView(APIView):
    """All chats for the sidebar, most recently active first."""

    @extend_schema(summary="Chat list", responses=ConversationSerializer(many=True))
    def get(self, request):
        conversations = Conversation.objects.all()[:100]
        return Response(ConversationSerializer(conversations, many=True).data)


class ConversationDetailView(APIView):
    """One chat with its full history, to reopen it."""

    @extend_schema(
        summary="One chat with its messages and cards",
        responses=inline_serializer(
            "ConversationDetail",
            {
                "thread_id": serializers.CharField(),
                "title": serializers.CharField(),
                "created_at": serializers.DateTimeField(),
                "updated_at": serializers.DateTimeField(),
                "messages": serializers.ListField(child=serializers.DictField()),
            },
        ),
    )
    def get(self, request, thread_id: str):
        conversation = get_object_or_404(Conversation, thread_id=thread_id)
        return Response(
            {**ConversationSerializer(conversation).data, "messages": load_messages(thread_id)}
        )


class TranscribeView(APIView):
    """
    Speech to text for the mic button. The UI sends the growing recording every ~1.5 s,
    so the text appears while the user is still talking.
    """

    parser_classes = [MultiPartParser]
    throttle_classes = [TranscribeRateThrottle]

    @extend_schema(
        summary="Speech to text (WAV, up to 3 MB)",
        request={"multipart/form-data": TranscribeSerializer},
        responses={
            200: inline_serializer("Transcript", {"text": serializers.CharField()}),
            502: inline_serializer("TranscribeError", {"detail": serializers.CharField()}),
        },
    )
    def post(self, request):
        serializer = TranscribeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        audio = cast(dict, serializer.validated_data)["audio"]  # DRF has no type hints

        try:
            text = transcribe(audio.read())
        except TranscriptionError:
            logger.exception("Transcription failed")
            return Response(
                {"detail": "تبدیل صدا به متن انجام نشد. دوباره تلاش کن."},
                status=status.HTTP_502_BAD_GATEWAY,
            )
        return Response({"text": text})
