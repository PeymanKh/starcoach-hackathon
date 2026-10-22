import logging

from celery import shared_task

from apps.agents.agent import build_agent
from apps.agents.context import UserContext
from apps.agents.events import stream_events
from apps.agents.llm import DEFAULT_MODEL, DEFAULT_THINKING
from apps.agents.runs import publish

logger = logging.getLogger(__name__)


@shared_task
def ping() -> str:
    return "pong"


@shared_task(ignore_result=True)
def run_agent(
    run_id: str,
    thread_id: str,
    message: str,
    lat: float | None = None,
    lon: float | None = None,
    model_key: str = DEFAULT_MODEL,
    thinking: str = DEFAULT_THINKING,
    user_id: str | None = None,
) -> None:
    """
    Run the agent on one user message and publish every UI event to the run's stream.

    Arguments are plain values because Celery sends them as JSON. Every run ends with
    "done" or "error", so the browser always knows when to stop listening.
    """

    try:
        agent = build_agent(model_key, thinking)
        context = UserContext(user_id=user_id, lat=lat, lon=lon)
        for event in stream_events(agent, message, thread_id, context):
            publish(run_id, event)

    except Exception:
        logger.exception("Agent run %s failed", run_id)
        publish(run_id, {"event": "error", "message": "مشکلی پیش آمد. لطفاً دوباره تلاش کنید."})
        return

    publish(run_id, {"event": "done", "thread_id": thread_id})
