"""The UI runs on another origin (Vercel), so the API must allow exactly that origin."""

import pytest

UI = "https://starcoach.vercel.app"


@pytest.fixture(autouse=True)
def ui_origin(settings):
    settings.CORS_ALLOWED_ORIGINS = [UI]


def test_the_ui_origin_may_read_responses(client):
    response = client.get("/api/agent/models/", HTTP_ORIGIN=UI)
    assert response["Access-Control-Allow-Origin"] == UI


def test_other_origins_get_no_cors_header(client):
    response = client.get("/api/agent/models/", HTTP_ORIGIN="https://evil.example")
    assert "Access-Control-Allow-Origin" not in response


def test_preflight_allows_last_event_id_for_stream_resume(client):
    # A dropped SSE stream reconnects with Last-Event-ID, so the header must be allowed.
    response = client.options(
        "/api/agent/models/",
        HTTP_ORIGIN=UI,
        HTTP_ACCESS_CONTROL_REQUEST_METHOD="GET",
        HTTP_ACCESS_CONTROL_REQUEST_HEADERS="last-event-id",
    )
    assert response.status_code == 200
    assert "last-event-id" in response["Access-Control-Allow-Headers"]
