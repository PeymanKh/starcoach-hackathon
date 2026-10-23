from typing import cast
from uuid import uuid4

from celery import Task
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.views import View
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.agents.api.serializers import ConversationSerializer, RunCreateSerializer
from apps.agents.api.sse import event_stream
from apps.agents.api.throttles import RunRateThrottle
from apps.agents.history import load_messages
from apps.agents.llm import DEFAULT_MODEL, DEFAULT_THINKING, MODELS, THINKING_LEVELS
from apps.agents.models import Conversation
from apps.agents.tasks import run_agent


class ModelListView(APIView):
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

    def get(self, request):
        conversations = Conversation.objects.all()[:100]
        return Response(ConversationSerializer(conversations, many=True).data)


class ConversationDetailView(APIView):
    """One chat with its full history, to reopen it."""

    def get(self, request, thread_id: str):
        conversation = get_object_or_404(Conversation, thread_id=thread_id)
        return Response(
            {**ConversationSerializer(conversation).data, "messages": load_messages(thread_id)}
        )
