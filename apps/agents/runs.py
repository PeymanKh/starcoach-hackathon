"""
Agent runs live in Redis Streams: the Celery worker appends events, the SSE view reads them.

A stream keeps its events (unlike pub/sub), so a browser that connects late or reconnects
after a refresh still gets every event, starting after the last one it saw.
"""

import json
from functools import cache
from typing import cast

import redis
from django.conf import settings

RUN_TTL_SECONDS = 60 * 60  # keep a run's events for an hour, long enough to reconnect


@cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)


def stream_key(run_id: str) -> str:
    return f"agent:run:{run_id}"


def publish(run_id: str, event: dict) -> None:
    """Append one event to the run's stream and keep the stream alive for RUN_TTL_SECONDS."""

    client = get_redis()
    key = stream_key(run_id)
    client.xadd(key, {"data": json.dumps(event, ensure_ascii=False)})
    client.expire(key, RUN_TTL_SECONDS)


def read_events(run_id: str, after: str = "0", block_ms: int = 15_000) -> list[tuple[str, dict]]:
    """
    The run's events after the stream id `after` ("0" means from the start).

    Waits up to `block_ms` for new events and returns [] if none came, so the caller can
    send a heartbeat. Each event comes with its stream id, which the browser uses to resume.
    """

    response = cast(list, get_redis().xread({stream_key(run_id): after}, block=block_ms, count=100))
    if not response:
        return []
    _key, entries = response[0]
    return [(event_id, json.loads(fields["data"])) for event_id, fields in entries]
