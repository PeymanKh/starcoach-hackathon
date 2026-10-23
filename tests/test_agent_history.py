"""Chats for the sidebar and reopening a chat with its history."""

import json

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver

from apps.agents import history
from apps.agents.api import views
from apps.agents.history import to_ui_messages
from apps.agents.models import TITLE_LENGTH, Conversation


@pytest.fixture
def queued(monkeypatch):
    class FakeTask:
        def delay(self, **kwargs):
            pass

    monkeypatch.setattr(views, "run_agent", FakeTask())


def start(client, **body):
    return client.post("/api/agent/runs/", body, content_type="application/json").json()


def test_agent_memory_becomes_the_chat_the_user_saw():
    card = {"type": "product_list", "products": [{"id": "p1"}]}
    raw = [
        HumanMessage("یه گوشی"),
        AIMessage(
            content="بذار جستجو کنم…",  # said together with the tool calls: not part of the answer
            tool_calls=[
                {"name": "search_products", "args": {"query": "گوشی"}, "id": "c1"},
                {"name": "find_stores", "args": {"product_id": "p1"}, "id": "c2"},
            ],
        ),
        ToolMessage(json.dumps(card), tool_call_id="c1", name="search_products"),
        ToolMessage("Tool error: db down", tool_call_id="c2", name="find_stores", status="error"),
        AIMessage("این خوبه [[product:p1]]"),
        HumanMessage("ممنون"),
        AIMessage("خواهش می‌کنم"),
    ]

    assert to_ui_messages(raw) == [
        {"role": "user", "text": "یه گوشی"},
        {
            "role": "assistant",
            "text": "این خوبه [[product:p1]]",
            "steps": [
                # args come back too, so a reopened chat shows what each tool was asked for
                {
                    "id": "c1",
                    "tool": "search_products",
                    "args": {"query": "گوشی"},
                    "status": "done",
                    "ui": card,
                },
                {
                    "id": "c2",
                    "tool": "find_stores",
                    "args": {"product_id": "p1"},
                    "status": "failed",
                    "ui": None,
                },
            ],
            "status": "done",
        },
        {"role": "user", "text": "ممنون"},
        {"role": "assistant", "text": "خواهش می‌کنم", "steps": [], "status": "done"},
    ]


def test_a_chat_with_no_memory_yet_has_no_messages(monkeypatch):
    monkeypatch.setattr(history, "get_checkpointer", InMemorySaver)
    assert history.load_messages("never-ran") == []


def test_first_message_creates_the_chat_titled_by_it(client, db, queued):
    long_message = "سلام " * 50
    body = start(client, message=long_message)

    conversation = Conversation.objects.get(thread_id=body["thread_id"])
    assert conversation.title == long_message[:TITLE_LENGTH]


def test_later_messages_keep_the_title_and_move_the_chat_to_the_top(client, db, queued):
    first = start(client, message="اولین گفتگو")["thread_id"]
    second = start(client, message="دومین گفتگو")["thread_id"]
    start(client, message="ادامه‌ی اولی", thread_id=first)

    chats = client.get("/api/agent/threads/").json()
    assert [(c["thread_id"], c["title"]) for c in chats] == [
        (first, "اولین گفتگو"),
        (second, "دومین گفتگو"),
    ]


def test_reopening_a_chat_returns_its_messages(client, db, queued, monkeypatch):
    thread_id = start(client, message="سلام")["thread_id"]
    messages = [{"role": "user", "text": "سلام"}]
    monkeypatch.setattr(views, "load_messages", lambda tid: messages if tid == thread_id else [])

    body = client.get(f"/api/agent/threads/{thread_id}/").json()
    assert (body["title"], body["messages"]) == ("سلام", messages)


def test_unknown_chat_is_404(client, db):
    assert client.get("/api/agent/threads/nope/").status_code == 404
