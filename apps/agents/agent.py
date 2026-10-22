import os
from collections.abc import Callable
from functools import cache

from langchain.agents import create_agent
from langchain.agents.middleware import AgentMiddleware, AgentState
from langchain.messages import ToolMessage
from langchain.tools.tool_node import ToolCallRequest
from langgraph.checkpoint.postgres import PostgresSaver
from langgraph.types import Command
from psycopg import Connection
from psycopg.rows import DictRow, dict_row
from psycopg_pool import ConnectionPool

from apps.agents.context import UserContext
from apps.agents.llm import DEFAULT_MODEL, DEFAULT_THINKING, build_model
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

SYSTEM_PROMPT = """You are Torob's assistant for in-person shopping in Tehran's stores and malls.
Always answer in Persian, short and friendly.

How you work:
- Help the user figure out what they need (use, budget), find stores near them, compare, choose.
- Use only facts from tool results. Never invent products, prices, stores or opening hours.
- Prices are listed prices, not confirmed stock: say how old a price is and suggest calling
  the store before going.
- Without the user's location, distances are unknown: ask them to share it for nearby stores.

Showing cards:
- The UI turns products and stores from tool results into cards. To show one inside your
  answer, write its marker on its own line: [[product:PRODUCT_ID]] or [[store:STORE_ID]]
- Use only ids that appeared in tool results. Don't repeat what the card already shows
  (price, address, hours); explain why it fits the user.
"""


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


def build_agent(model_key: str = DEFAULT_MODEL, thinking: str = DEFAULT_THINKING):
    """A ready agent for one run, with the model and thinking level the user picked."""

    return create_agent(
        model=build_model(model_key, thinking),
        tools=TOOLS,
        system_prompt=SYSTEM_PROMPT,
        context_schema=UserContext,
        checkpointer=get_checkpointer(),
        middleware=[HandleToolErrors()],
    )
