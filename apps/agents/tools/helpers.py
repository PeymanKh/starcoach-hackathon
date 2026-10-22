import math
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

TEHRAN = ZoneInfo("Asia/Tehran")
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Straight-line distance between two points, in km."""

    lat1, lon1, lat2, lon2 = map(math.radians, (lat1, lon1, lat2, lon2))
    a = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return round(6371 * 2 * math.asin(math.sqrt(a)), 2)


def price_freshness(changed_at: datetime | None, now: datetime | None = None) -> dict:
    """
    How reliable a listed price is?

    last update <= 10 days: fresh
    last update <= 30 days: recent
    last update <= 180 days: old
    last update > 180 days: very_old
    """

    if changed_at is None:
        return {"label": "unknown", "days_ago": None, "changed_at": None}

    now = now or datetime.now(TEHRAN)
    days = (now - changed_at).days

    if days <= 10:
        label = "fresh"
    elif days <= 30:
        label = "recent"
    elif days <= 180:
        label = "old"
    else:
        label = "very_old"
    changed_on = changed_at.astimezone(TEHRAN).date().isoformat()

    return {"label": label, "days_ago": days, "changed_at": changed_on}


def opening_status(hours: list, now: datetime | None = None) -> dict:
    """Is the shop open right now?"""

    if not hours:
        return {"state": "unknown"}

    now = (now or datetime.now(TEHRAN)).astimezone(TEHRAN)

    by_day: dict[str, list] = {}
    for row in hours:
        by_day.setdefault(row.day, []).append(row)

    today = by_day.get(DAYS[now.weekday()], [])
    if any(row.status == "unsupported" for row in today):
        return {"state": "unknown"}

    # A day can have two shifts (lunch break), so check each one.
    for row in today:
        if row.status == "declared" and row.start_time <= now.time() < row.end_time:
            closes = datetime.combine(now.date(), row.end_time, TEHRAN)
            return {
                "state": "open",
                "closes_at": row.end_time.strftime("%H:%M"),
                "minutes_to_close": int((closes - now).total_seconds() // 60),
            }

    # Closed now: find the next shift start in the coming week.
    for offset in range(8):
        day = now + timedelta(days=offset)
        starts = sorted(
            row.start_time
            for row in by_day.get(DAYS[day.weekday()], [])
            if row.status == "declared" and (offset > 0 or row.start_time > now.time())
        )
        if starts:
            return {
                "state": "closed",
                "opens_day": DAYS[day.weekday()],
                "opens_at": starts[0].strftime("%H:%M"),
                "opens_today": offset == 0,
            }
    return {"state": "closed"}


def paginate(items: list, page: int, page_size: int) -> dict:
    """Cut a list into one page and say whether there is more."""

    page_size = max(1, min(page_size, 20))
    page = max(page, 1)
    start = (page - 1) * page_size
    return {
        "total": len(items),
        "page": page,
        "page_size": page_size,
        "has_more": start + page_size < len(items),
        "items": items[start : start + page_size],
    }
