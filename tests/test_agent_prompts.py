"""The system prompt: its Markdown parts, and what is injected for every message."""

from datetime import UTC, datetime

import pytest

from apps.agents.context import UserContext
from apps.agents.prompts import FOLDER, PARTS, build_system_prompt, context_prompt
from apps.agents.tools.helpers import TEHRAN

FRIDAY = datetime(2026, 10, 23, 15, 30, tzinfo=TEHRAN)  # 1 Aban 1405
SATURDAY = datetime(2026, 10, 24, 9, 5, tzinfo=TEHRAN)
HERE = UserContext(lat=35.7, lon=51.4)


def test_every_part_is_a_file_and_lands_in_the_prompt():
    # A renamed or missing part would break every message, so check them all.
    prompt = build_system_prompt(HERE)
    for part in PARTS:
        assert (FOLDER / f"{part}.md").read_text(encoding="utf-8").strip() in prompt


def test_date_is_persian_and_gregorian_with_tehran_time():
    text = context_prompt(HERE, now=FRIDAY)
    assert "جمعه 1 آبان 1405" in text
    assert "Friday, 23 October 2026" in text
    assert "15:30" in text


def test_a_utc_server_still_gives_the_date_and_time_in_tehran():
    # 23:00 UTC on Friday is already Saturday 02:30 in Tehran.
    text = context_prompt(HERE, now=datetime(2026, 10, 23, 23, 0, tzinfo=UTC))
    assert "شنبه 2 آبان 1405" in text
    assert "02:30" in text


def test_friday_warning_only_on_fridays():
    assert "weekend" in context_prompt(HERE, now=FRIDAY)
    assert "weekend" not in context_prompt(HERE, now=SATURDAY)


@pytest.mark.parametrize(
    ("context", "shared"),
    [(HERE, True), (UserContext(), False), (UserContext(lat=35.7), False)],
    ids=["shared", "not shared", "half a location"],
)
def test_location_shared_or_not(context, shared):
    text = context_prompt(context, now=SATURDAY)
    assert ("nearest shops are available" in text) is shared
    assert ("location is unknown" in text) is not shared


def test_no_context_at_all_means_no_location():
    assert "location is unknown" in build_system_prompt(None)
