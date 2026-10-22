import json
import time
from collections.abc import Iterator

from apps.agents.runs import read_events

HEARTBEAT_MS = 15_000
MAX_STREAM_SECONDS = 300
TIMEOUT_EVENT = {"event": "error", "message": "پاسخی دریافت نشد. لطفاً دوباره تلاش کنید."}


def format_event(event: dict, event_id: str | None = None) -> str:
    """One SSE message. The id lets the browser resume right after it."""

    data = f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
    return f"id: {event_id}\n{data}" if event_id else data


def event_stream(run_id: str, after: str = "0") -> Iterator[str]:
    """Relay the run's events after the id `after`, until "done" or "error"."""

    deadline = time.monotonic() + MAX_STREAM_SECONDS
    yield "retry: 2000\n\n"  # if the connection drops, the browser reconnects after 2 s
    while time.monotonic() < deadline:
        events = read_events(run_id, after=after, block_ms=HEARTBEAT_MS)
        if not events:
            yield ": keep-alive\n\n"  # an SSE comment: ignored by the browser
            continue
        for event_id, event in events:
            after = event_id
            yield format_event(event, event_id)
            if event["event"] in ("done", "error"):
                return
    yield format_event(TIMEOUT_EVENT)
