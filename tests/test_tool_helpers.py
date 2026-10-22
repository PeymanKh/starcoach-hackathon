"""Pure helpers behind the agent tools. No database needed."""

from datetime import UTC, datetime, time, timedelta
from types import SimpleNamespace

import pytest

from apps.agents.tools.helpers import (
    TEHRAN,
    distance_km,
    opening_status,
    paginate,
    price_freshness,
)
from apps.catalog.text import normalize_for_search

# 2026-10-24 is a Saturday.
SATURDAY = datetime(2026, 10, 24, tzinfo=TEHRAN)


def hours(day, status, start=None, end=None):
    """A fake ShopWorkingHours row."""
    return SimpleNamespace(day=day, status=status, start_time=start, end_time=end)


def at(day: datetime, hh: int, mm: int = 0) -> datetime:
    return day.replace(hour=hh, minute=mm)


# A shop with a lunch break on Saturday, closed on Friday.
SPLIT_SHIFT = [
    hours("sat", "declared", time(9), time(13)),
    hours("sat", "declared", time(16), time(21)),
    hours("fri", "closed"),
]


def test_normalize_for_search_unifies_what_users_type():
    # Arabic ي/ك, آ, Persian digits, half-space and uppercase must all match the data.
    assert normalize_for_search("آيفون ۱۵", "Pro‌Max") == "ایفون 15 pro max"
    assert normalize_for_search(None, "", "سامسونگ") == "سامسونگ"


def test_distance_km():
    assert distance_km(35.7, 51.4, 35.7, 51.4) == 0
    # One degree of latitude is about 111.2 km anywhere on Earth.
    assert distance_km(35.0, 51.4, 36.0, 51.4) == pytest.approx(111.2, abs=0.1)


@pytest.mark.parametrize(
    ("days_ago", "label"),
    [(0, "fresh"), (10, "fresh"), (11, "recent"), (30, "recent"), (31, "old"), (181, "very_old")],
)
def test_price_freshness_labels(days_ago, label):
    now = at(SATURDAY, 12)
    result = price_freshness(now - timedelta(days=days_ago), now=now)
    assert result["label"] == label
    assert result["days_ago"] == days_ago


def test_price_freshness_unknown_date():
    assert price_freshness(None)["label"] == "unknown"


def test_open_during_a_shift():
    assert opening_status(SPLIT_SHIFT, now=at(SATURDAY, 20, 15)) == {
        "state": "open",
        "closes_at": "21:00",
        "minutes_to_close": 45,
    }


def test_closed_during_lunch_break_reopens_today():
    result = opening_status(SPLIT_SHIFT, now=at(SATURDAY, 14))
    assert result == {
        "state": "closed",
        "opens_day": "sat",
        "opens_at": "16:00",
        "opens_today": True,
    }


def test_closed_day_points_to_next_opening():
    friday = SATURDAY + timedelta(days=6)
    result = opening_status(SPLIT_SHIFT, now=at(friday, 11))
    assert result == {
        "state": "closed",
        "opens_day": "sat",
        "opens_at": "09:00",
        "opens_today": False,
    }


def test_uses_tehran_time_not_server_time():
    # 06:00 UTC is 09:30 in Tehran: open. A UTC server must not call it closed.
    now = datetime(2026, 10, 24, 6, 0, tzinfo=UTC)
    assert opening_status(SPLIT_SHIFT, now=now)["state"] == "open"


@pytest.mark.parametrize(
    "rows",
    [[], [hours("sat", "unsupported")]],
    ids=["no hours", "unsupported hours"],
)
def test_unknown_hours_are_never_guessed(rows):
    assert opening_status(rows, now=at(SATURDAY, 12)) == {"state": "unknown"}


def test_paginate():
    items = list(range(25))
    first = paginate(items, page=1, page_size=10)
    last = paginate(items, page=3, page_size=10)
    assert (first["total"], first["has_more"], first["items"]) == (25, True, list(range(10)))
    assert (last["has_more"], last["items"]) == (False, [20, 21, 22, 23, 24])
    # Bad input from the model is clamped, not trusted.
    assert paginate(items, page=0, page_size=500)["page"] == 1
    assert paginate(items, page=1, page_size=500)["page_size"] == 20
