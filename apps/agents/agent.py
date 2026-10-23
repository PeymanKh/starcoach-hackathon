import os
from collections.abc import Callable
from functools import cache
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    AgentState,
    ClearToolUsesEdit,
    ContextEditingMiddleware,
    ModelFallbackMiddleware,
    ModelRequest,
    ToolCallLimitMiddleware,
    dynamic_prompt,
)
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from apps.agents.context import UserContext
from apps.agents.llm import DEFAULT_MODEL, DEFAULT_THINKING, build_model
from apps.agents.prompts import build_system_prompt
from apps.agents.tools.products import (
    compare_products,
    explore_category,
    find_alternatives,
    get_product_details,
    search_products,
)
from apps.agents.tools.stores import (
    compare_stores,
    find_stores,
    find_stores_by_category,
    get_store_details,
)

TOOLS = [
    explore_category,
    search_products,
    get_product_details,
    compare_products,
    find_alternatives,
    find_stores,
    find_stores_by_category,
    get_store_details,
    compare_stores,
]


# Old tool results (product and store lists) are the bulk of a long chat. Above this size,
# the model sees only the latest few in full, and older ones become a short placeholder.
# Only what is sent to the model changes: the saved chat, its cards and history stay whole.
COMPACT_AFTER_TOKENS = 30_000
KEEP_TOOL_RESULTS = 4


# At most this many tool calls per message. After that the model must answer with what it has.
MAX_TOOL_CALLS = 8

# If the chosen model fails, answer with this one (or the second, if the first was chosen).
BACKUP_MODEL = "claude-sonnet-5.5"
SECOND_BACKUP_MODEL = "gpt-6-luna"


class HandleToolErrors(AgentMiddleware[AgentState, UserContext]):
    """A crashing tool must not crash the conversation: tell the model so it can recover."""

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        try:
            return handler(request)
        except Exception as e:
            return ToolMessage(
                content=f"Tool error: {e}. Tell the user briefly and try another way.",
                tool_call_id=request.tool_call["id"],
                status="error",
            )


@cache
def get_checkpointer() -> PostgresSaver:
    """Conversation memory in Postgres. One connection pool per process, made on first use."""

    pool = ConnectionPool(
        os.environ["DATABASE_URL"],
        connection_class=Connection[DictRow],
        max_size=10,
        open=True,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    checkpointer = PostgresSaver(pool)
    checkpointer.setup()
    return checkpointer


@dynamic_prompt
def system_prompt(request: ModelRequest[UserContext]) -> str:
    """Built for every model call, so the date and time are always current."""

    return build_system_prompt(request.runtime.context)


def build_agent(model_key: str = DEFAULT_MODEL, thinking: str = DEFAULT_THINKING):
    """A ready agent for one run, with the model and thinking level the user picked."""

    backup = BACKUP_MODEL if model_key != BACKUP_MODEL else SECOND_BACKUP_MODEL

    # Outermost first: the prompt and the trimming apply to whichever model answers.
    # Typed loosely: the library types some middleware with their own state and no context,
    # which pyright can't fit into one list with ours, though they work together fine.
    middleware: list[AgentMiddleware[Any, Any, Any]] = [
        system_prompt,
        ContextEditingMiddleware(
            edits=[ClearToolUsesEdit(trigger=COMPACT_AFTER_TOKENS, keep=KEEP_TOOL_RESULTS)]
        ),
        ToolCallLimitMiddleware(run_limit=MAX_TOOL_CALLS, exit_behavior="continue"),
        ModelFallbackMiddleware(build_model(backup, thinking)),
        HandleToolErrors(),
    ]

    return create_agent(
        model=build_model(model_key, thinking),
        tools=TOOLS,
        context_schema=UserContext,
        checkpointer=get_checkpointer(),
        middleware=middleware,
    )
