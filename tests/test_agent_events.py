"""The UI event stream, driven by a fake model: no LLM, no network, no cost."""

import json

from langchain.agents import create_agent
from langchain.tools import tool
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk
from langchain_core.messages.tool import tool_call_chunk
from langchain_core.outputs import ChatGenerationChunk
from langgraph.checkpoint.memory import InMemorySaver

from apps.agents.agent import HandleToolErrors
from apps.agents.context import UserContext
from apps.agents.events import stream_events


class ScriptedModel(BaseChatModel):
    """Plays back a fixed list of replies, streaming text word by word like a real model."""

    replies: list
    turn: int = 0

    @property
    def _llm_type(self):
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError  # the agent always streams

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        reply = self.replies[self.turn]
        self.turn += 1
        if isinstance(reply, AIMessage) and reply.tool_calls:
            chunks = [
                tool_call_chunk(name=c["name"], args=json.dumps(c["args"]), id=c["id"], index=i)
                for i, c in enumerate(reply.tool_calls)
            ]
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=chunks))
            return
        if reply == "THINK":
            # ChatOpenRouter streams reasoning this way: in additional_kwargs, content stays text.
            for piece in ["Let me ", "think..."]:
                thought = AIMessageChunk(content="", additional_kwargs={"reasoning_content": piece})
                yield ChatGenerationChunk(message=thought)
            reply = self.replies[self.turn]
            self.turn += 1
        assert isinstance(reply, str)
        for word in reply.split(" "):
            yield ChatGenerationChunk(message=AIMessageChunk(content=word + " "))


@tool
def search_products(query: str) -> dict:
    """Search products."""
    return {"type": "product_list", "products": [{"id": "p1"}]}


@tool
def broken_tool(x: str) -> dict:
    """Always fails."""
    raise ValueError("database is down")


def run(replies):
    model = ScriptedModel(replies=replies)
    agent = create_agent(
        model=model,
        tools=[search_products, broken_tool],
        context_schema=UserContext,
        checkpointer=InMemorySaver(),
        middleware=[HandleToolErrors()],
    )
    return list(stream_events(agent, "سلام", "thread-1", UserContext()))


def test_tool_calls_cards_and_streamed_answer():
    calls = [
        {"name": "search_products", "args": {"query": "آیفون"}, "id": "c1"},
        {"name": "broken_tool", "args": {"x": "1"}, "id": "c2"},
    ]
    events = run([AIMessage(content="", tool_calls=calls), "این دو [[product:p1]] خوبن"])

    starts = [e for e in events if e["event"] == "tool_start"]
    ends = {e["id"]: e for e in events if e["event"] == "tool_end"}
    text = "".join(e["text"] for e in events if e["event"] == "token")

    assert [(s["id"], s["tool"], s["args"]) for s in starts] == [
        ("c1", "search_products", {"query": "آیفون"}),
        ("c2", "broken_tool", {"x": "1"}),
    ]
    # The card data arrives as a dict, ready for the UI.
    assert ends["c1"] == {
        "event": "tool_end",
        "id": "c1",
        "tool": "search_products",
        "ok": True,
        "ui": {"type": "product_list", "products": [{"id": "p1"}]},
    }
    # A crashing tool becomes a failed step, not a crashed run, and has no card.
    assert (ends["c2"]["ok"], ends["c2"]["ui"]) == (False, None)
    # Text streams word by word, after the tools, with the card marker intact.
    assert text.strip() == "این دو [[product:p1]] خوبن"
    assert events.index(ends["c2"]) < next(i for i, e in enumerate(events) if e["event"] == "token")


def test_thinking_is_announced_once_before_the_answer():
    events = run(["THINK", "سلام!"])
    kinds = [e["event"] for e in events]
    assert kinds[0] == "thinking"
    assert kinds.count("thinking") == 1
    assert "".join(e["text"] for e in events if e["event"] == "token").strip() == "سلام!"
