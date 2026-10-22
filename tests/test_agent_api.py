"""The two endpoints the UI talks to: start a run, then stream its events."""

import json

import fakeredis
import pytest
from django.core.cache import cache

from apps.agents import runs
from apps.agents.api import sse, views

RUN_ID = "a" * 32


@pytest.fixture(autouse=True)
def fresh_rate_limit():
    cache.clear()  # the run rate limit counts requests in Django's cache


@pytest.fixture
def queued(monkeypatch):
    """Capture runs instead of sending them to Celery."""
    calls = []

    class FakeTask:
        def delay(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(views, "run_agent", FakeTask())
    return calls


@pytest.fixture
def redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(runs, "get_redis", lambda: client)
    # Short waits, so a stream that fails to stop makes the test fail instead of hang.
    monkeypatch.setattr(sse, "HEARTBEAT_MS", 10)
    monkeypatch.setattr(sse, "MAX_STREAM_SECONDS", 1)
    return client


def start(client, **body):
    return client.post("/api/agent/runs/", body, content_type="application/json")


def read_stream(response) -> tuple[str, list[dict], list[str]]:
    """Consume an SSE response: the raw text, the JSON events and their ids."""
    body = b"".join(response.streaming_content).decode()
    lines = body.splitlines()
    events = [json.loads(line[6:]) for line in lines if line.startswith("data: ")]
    ids = [line[4:] for line in lines if line.startswith("id: ")]
    return body, events, ids


def test_models_menu(client):
    data = client.get("/api/agent/models/").json()
    assert {"key": "claude-sonnet-5.5", "label": "Claude Sonnet 5.5"} in data["models"]
    assert data["thinking_levels"] == ["low", "medium", "high"]


def test_start_run_queues_the_agent_with_the_users_choices(client, queued):
    response = start(
        client, message="یه گوشی", thread_id="t-1", model="gpt-6-luna", thinking="high",
        lat=35.7, lon=51.4,
    )  # fmt: skip
    assert response.status_code == 202
    body = response.json()
    assert body["thread_id"] == "t-1"
    assert body["stream_url"] == f"/api/agent/runs/{body['run_id']}/stream/"
    assert queued == [
        {
            "run_id": body["run_id"],
            "thread_id": "t-1",
            "message": "یه گوشی",
            "lat": 35.7,
            "lon": 51.4,
            "model_key": "gpt-6-luna",
            "thinking": "high",
        }
    ]


def test_first_message_starts_a_new_conversation_with_defaults(client, queued):
    body = start(client, message="سلام").json()
    assert len(body["thread_id"]) == 32
    assert (queued[0]["model_key"], queued[0]["thinking"]) == ("claude-sonnet-5.5", "low")
    assert (queued[0]["lat"], queued[0]["lon"]) == (None, None)


@pytest.mark.parametrize(
    "body",
    [
        {"message": ""},
        {"message": "سلام", "model": "some/expensive-model"},  # only whitelisted models
        {"message": "سلام", "lat": 35.7},  # lat without lon
        {"message": "سلام", "thread_id": "../../etc"},
    ],
    ids=["empty message", "unknown model", "half a location", "bad thread id"],
)
def test_bad_requests_are_rejected_before_any_cost(client, queued, body):
    assert start(client, **body).status_code == 400
    assert queued == []


def test_runs_are_rate_limited(client, queued):
    codes = [start(client, message="سلام").status_code for _ in range(11)]
    assert codes == [202] * 10 + [429]
    assert len(queued) == 10


def test_stream_sends_events_in_sse_format_and_stops_at_done(client, redis):
    runs.publish(RUN_ID, {"event": "token", "text": "سلام"})
    runs.publish(RUN_ID, {"event": "done", "thread_id": "t-1"})
    runs.publish(RUN_ID, {"event": "token", "text": "never sent"})

    response = client.get(f"/api/agent/runs/{RUN_ID}/stream/")
    assert response["Content-Type"] == "text/event-stream"
    assert response["X-Accel-Buffering"] == "no"
    body, events, ids = read_stream(response)

    assert body.startswith("retry: 2000\n\n")  # browser reconnects after 2 s if dropped
    assert events == [{"event": "token", "text": "سلام"}, {"event": "done", "thread_id": "t-1"}]
    assert len(ids) == 2


def test_long_answers_arrive_once_and_in_order(client, redis):
    # Redis hands out at most 100 events per read: a long answer takes several reads.
    for n in range(150):
        runs.publish(RUN_ID, {"event": "token", "text": str(n)})
    runs.publish(RUN_ID, {"event": "done", "thread_id": "t-1"})

    _, events, ids = read_stream(client.get(f"/api/agent/runs/{RUN_ID}/stream/"))
    assert [e["text"] for e in events[:-1]] == [str(n) for n in range(150)]
    assert len(set(ids)) == 151


def test_stream_resumes_after_the_last_event_the_browser_saw(client, redis):
    runs.publish(RUN_ID, {"event": "token", "text": "اول"})
    runs.publish(RUN_ID, {"event": "token", "text": "دوم"})
    runs.publish(RUN_ID, {"event": "done", "thread_id": "t-1"})
    first_id = runs.read_events(RUN_ID, block_ms=10)[0][0]

    # EventSource reconnects with a header, a refreshed page passes ?after=
    by_header = client.get(f"/api/agent/runs/{RUN_ID}/stream/", HTTP_LAST_EVENT_ID=first_id)
    by_query = client.get(f"/api/agent/runs/{RUN_ID}/stream/?after={first_id}")
    for response in (by_header, by_query):
        _, events, _ = read_stream(response)
        assert [e.get("text") for e in events] == ["دوم", None]


def test_stream_keeps_alive_then_gives_up_on_a_run_that_never_ends(client, redis, monkeypatch):
    monkeypatch.setattr(sse, "MAX_STREAM_SECONDS", 0.1)

    response = client.get(f"/api/agent/runs/{RUN_ID}/stream/")
    body, events, _ = read_stream(response)

    assert ": keep-alive" in body
    assert [e["event"] for e in events] == ["error"]


def test_stream_rejects_malformed_run_ids(client):
    assert client.get("/api/agent/runs/not-a-run/stream/").status_code == 404
