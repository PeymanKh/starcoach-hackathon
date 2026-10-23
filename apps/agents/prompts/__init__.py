"""
The system prompt: fixed parts written in Markdown, plus what is true right now
(date and time in Tehran, whether the user shared their location).
"""

from datetime import datetime
from functools import cache
from pathlib import Path

import jdatetime

from apps.agents.context import UserContext
from apps.agents.tools.helpers import TEHRAN

PARTS = ["role_v1", "voice_v1", "workflow_v1", "tools_v1", "format_v1", "rules_v1"]

FOLDER = Path(__file__).parent

# Python's weekday() starts on Monday.
WEEKDAYS = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنجشنبه", "جمعه", "شنبه", "یکشنبه"]
MONTHS = [
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
]
FRIDAY = 4


@cache
def fixed_prompt() -> str:
    """The Markdown parts, read once per process."""

    texts = [(FOLDER / f"{part}.md").read_text(encoding="utf-8").strip() for part in PARTS]
    return "\n\n".join(texts)


def context_prompt(context: UserContext, now: datetime | None = None) -> str:
    """What changes with every message: the date and time, and the user's location."""

    now = (now or datetime.now(TEHRAN)).astimezone(TEHRAN)
    jalali = jdatetime.date.fromgregorian(date=now.date())

    lines = [
        "# Right now",
        f"- Date: {WEEKDAYS[now.weekday()]} {jalali.day} {MONTHS[jalali.month - 1]} {jalali.year}"
        f" ({now:%A, %d %B %Y})",
        f"- Time in Tehran: {now:%H:%M}",
    ]
    if now.weekday() == FRIDAY:
        lines.append("- It's Friday, the weekend in Iran: many shops are closed or open late.")

    if context.lat is not None and context.lon is not None:
        lines.append("- The user shared their location: distances and nearest shops are available.")
    else:
        lines.append(
            "- The user's location is unknown: shops are sorted by price, without distances."
        )
    return "\n".join(lines)


def build_system_prompt(context: UserContext | None) -> str:
    return f"{fixed_prompt()}\n\n{context_prompt(context or UserContext())}"
