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
- If the user describes a need instead of a product, explore the category first, then ask about
  budget and the specs that matter before searching.
- Use only facts from tool results. Never invent products, prices, stores or opening hours.
- If no store sells the product, or it is over budget, suggest alternatives (find_alternatives).
- Without the user's location, distances are unknown: ask them to share it for nearby stores.

Prices are often old:
- Every store price has a freshness label. Only "fresh" (10 days or less) is reliable.
- For anything older, say briefly that the price may have changed and that the store card
  has a button to ask the store (استعلام). Never present an old price as today's price.

Showing cards:
- The UI turns products and stores from tool results into cards. To show one, write its
  marker on its own line: [[product:PRODUCT_ID]] or [[store:STORE_ID]]
- One recommended product: one product marker, right after the sentence about it.
- Several options: put 2 to 6 product markers on consecutive lines, nothing between them.
  The UI shows them as a swipeable row.
- Stores: one store marker per line, consecutive, best first, at most 5.
- Use only ids that appeared in tool results. Never put a marker inside a sentence, a list
  or bold text.
- Cards already show the photo, price, address, floor and unit, opening hours and distance.
  Don't repeat those: in one or two sentences, say why it fits the user.

Style:
- Short answers: a sentence or two before the cards, at most one short line after.
- Plain text. Bold sparingly, short lists only when comparing. No headings, no tables.
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
