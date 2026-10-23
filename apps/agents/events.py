import json
from collections.abc import Iterator

from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage

from apps.agents.context import UserContext


def stream_events(agent, message: str, thread_id: str, context: UserContext) -> Iterator[dict]:
    """
    Run the agent on one user message and translate LangChain's stream into UI events.

    thinking: the model is reasoning before it answers
    token: a piece of the answer text
    tool_start: the agent called a tool (UI shows a status like "searching products...")
    tool_end: the tool finished: `ui` holds its result, the UI renders it as cards
    """

    stream = agent.stream(
        {"messages": [{"role": "user", "content": message}]},
        config={"configurable": {"thread_id": thread_id}},
        context=context,
        stream_mode=["messages", "updates"],
        version="v2",
    )
    thinking = False
    for chunk in stream:
        if chunk["type"] == "messages":
            token, _metadata = chunk["data"]
            if not isinstance(token, AIMessageChunk):
                continue  # tool results arrive complete in "updates"
            if not thinking and any(b["type"] == "reasoning" for b in token.content_blocks):
                thinking = True
                yield {"event": "thinking"}
            if token.text:
                thinking = False
                yield {"event": "token", "text": token.text}

        elif chunk["type"] == "updates":
            for node, update in chunk["data"].items():
                for msg in (update or {}).get("messages", []):
                    if node == "model" and isinstance(msg, AIMessage):
                        for call in msg.tool_calls:
                            thinking = False
                            yield {
                                "event": "tool_start",
                                "id": call["id"],
                                "tool": call["name"],
                                "args": call["args"],
                            }
                    elif node == "tools" and isinstance(msg, ToolMessage):
                        yield {
                            "event": "tool_end",
                            "id": msg.tool_call_id,
                            "tool": msg.name,
                            "ok": msg.status != "error",
                            "ui": card_data(msg.content),
                        }


def card_data(content) -> dict | None:
    """Our tools return dicts, which LangChain passes on as JSON text. Errors have no card."""

    if not isinstance(content, str):
        return None
    try:
        data = json.loads(content)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None
