from django.urls import path, re_path

from apps.agents.api.views import (
    ConversationDetailView,
    ConversationListView,
    ModelListView,
    RunCreateView,
    RunStreamView,
    TranscribeView,
)

app_name = "agents"

urlpatterns = [
    path("models/", ModelListView.as_view(), name="model-list"),
    path("runs/", RunCreateView.as_view(), name="run-create"),
    re_path(r"^runs/(?P<run_id>[0-9a-f]{32})/stream/$", RunStreamView.as_view(), name="run-stream"),
    path("threads/", ConversationListView.as_view(), name="conversation-list"),
    re_path(
        r"^threads/(?P<thread_id>[A-Za-z0-9_-]{1,64})/$",
        ConversationDetailView.as_view(),
        name="conversation-detail",
    ),
    path("transcribe/", TranscribeView.as_view(), name="transcribe"),
]
