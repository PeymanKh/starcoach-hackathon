from django.urls import path, re_path

from apps.agents.api.views import ModelListView, RunCreateView, RunStreamView

app_name = "agents"

urlpatterns = [
    path("models/", ModelListView.as_view(), name="model-list"),
    path("runs/", RunCreateView.as_view(), name="run-create"),
    re_path(r"^runs/(?P<run_id>[0-9a-f]{32})/stream/$", RunStreamView.as_view(), name="run-stream"),
]
