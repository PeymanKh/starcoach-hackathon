"""Agent runs through Redis Streams, with an in-memory Redis: no Redis server, no LLM."""

import fakeredis
import pytest

from apps.agents import runs, tasks
from apps.agents.context import UserContext


@pytest.fixture
def redis(monkeypatch):
    client = fakeredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(runs, "get_redis", lambda: client)
    return client


def test_events_come_back_in_order_and_can_resume(redis):
    runs.publish("r1", {"event": "token", "text": "سلام"})
    runs.publish("r1", {"event": "done", "thread_id": "t1"})

    events = runs.read_events("r1", block_ms=10)
    assert [e for _, e in events] == [
        {"event": "token", "text": "سلام"},
        {"event": "done", "thread_id": "t1"},
    ]
    # After a refresh the browser sends the last id it saw and gets only what came after.
    first_id = events[0][0]
    assert [e for _, e in runs.read_events("r1", after=first_id, block_ms=10)] == [
        {"event": "done", "thread_id": "t1"}
    ]
    # Runs don't pile up in Redis forever.
    assert 0 < redis.ttl(runs.stream_key("r1")) <= runs.RUN_TTL_SECONDS


def test_no_new_events_returns_empty_so_the_view_can_send_a_heartbeat(redis):
    assert runs.read_events("unknown-run", block_ms=10) == []


def test_run_publishes_every_event_then_done(redis, monkeypatch):
    seen = {}

    def fake_build_agent(model_key, thinking):
        seen["model"] = (model_key, thinking)
        return "agent"

    def fake_stream_events(agent, message, thread_id, context):
        seen["call"] = (agent, message, thread_id, context)
        yield {"event": "tool_start", "id": "c1", "tool": "search_products", "args": {}}
        yield {"event": "token", "text": "سلام"}

    monkeypatch.setattr(tasks, "build_agent", fake_build_agent)
    monkeypatch.setattr(tasks, "stream_events", fake_stream_events)

    tasks.run_agent(
        "r1", "t1", "یه گوشی", lat=35.7, lon=51.4, model_key="gpt-6-luna", thinking="high"
    )

    assert [e["event"] for _, e in runs.read_events("r1", block_ms=10)] == [
        "tool_start",
        "token",
        "done",
    ]
    # The browser's choices and location reach the agent.
    assert seen["model"] == ("gpt-6-luna", "high")
    assert seen["call"] == ("agent", "یه گوشی", "t1", UserContext(lat=35.7, lon=51.4))


def test_a_crashing_run_ends_with_an_error_event_not_silence(redis, monkeypatch):
    def broken_stream_events(agent, message, thread_id, context):
        yield {"event": "token", "text": "سل"}
        raise RuntimeError("OpenRouter is down")

    monkeypatch.setattr(tasks, "build_agent", lambda model_key, thinking: "agent")
    monkeypatch.setattr(tasks, "stream_events", broken_stream_events)

    tasks.run_agent("r2", "t2", "سلام")

    events = [e for _, e in runs.read_events("r2", block_ms=10)]
    assert [e["event"] for e in events] == ["token", "error"]
    assert "OpenRouter" not in events[-1]["message"]  # no internals shown to users
