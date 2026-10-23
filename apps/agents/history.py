"""A conversation's history, read back from the agent's memory, in the shape the UI renders."""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage

from apps.agents.agent import get_checkpointer
from apps.agents.events import card_data


def load_messages(thread_id: str) -> list[dict]:
    """The chat as the UI shows it: user messages, and assistant messages with their steps."""
    saved = get_checkpointer().get_tuple({"configurable": {"thread_id": thread_id}})
    if saved is None:
        return []
    return to_ui_messages(saved.checkpoint["channel_values"].get("messages", []))


def to_ui_messages(messages: list[BaseMessage]) -> list[dict]:
    """Group the raw agent messages into turns: one user message, then one assistant message
    holding the steps (tool calls) and the text of everything the agent did for it."""
    result: list[dict] = []
    assistant: dict | None = None

    for message in messages:
        if isinstance(message, HumanMessage):
            result.append({"role": "user", "text": message.text})
            assistant = None
            continue

        if assistant is None:
            assistant = {"role": "assistant", "text": "", "steps": [], "status": "done"}
            result.append(assistant)

        if isinstance(message, AIMessage):
            if message.text:
                assistant["text"] = message.text
            for call in message.tool_calls:
                step = {"id": call["id"], "tool": call["name"], "status": "running", "ui": None}
                assistant["steps"].append(step)
        elif isinstance(message, ToolMessage):
            for step in assistant["steps"]:
                if step["id"] == message.tool_call_id:
                    step["status"] = "failed" if message.status == "error" else "done"
                    step["ui"] = card_data(message.content)

    return result
