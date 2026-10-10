"""What is new on the dashboard.

Every build records when each item (a Lineup name, a setup, an insider or Congress buy, a verdict,
a theme update) first showed up in `seen.json`. An item counts as new for 36 weekday hours, so a
name added by the evening refresh is still marked NEW in the next morning brief, and a Friday
addition is still NEW on Monday morning.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

NEW_HOURS = 36
OLD = "2000-01-01T00:00+00:00"  # first_seen for everything on the very first run, so nothing floods as new


def _weekday_hours(start: datetime, end: datetime) -> float:
    hours, t = 0.0, start
    while t < end:
        step = min(end, (t + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0))
        if t.weekday() < 5:
            hours += (step - t).total_seconds() / 3600
        t = step
    return hours


def is_new(first: str, now: datetime) -> bool:
    return _weekday_hours(datetime.fromisoformat(first), now) <= NEW_HOURS


def track(seen: dict, current: dict[str, str], now: datetime | None = None) -> tuple[dict, dict]:
    """current maps item key to a value (a verdict, a theme note, or "1").
    Returns the updated seen record and {key: {"was": old value or None}} for items that are new right now,
    plus "_gone" with keys that dropped off inside the window."""
    now = now or datetime.now(timezone.utc)
    stamp = now.isoformat(timespec="minutes")
    first_run = not seen.get("items")
    items, gone = dict(seen.get("items", {})), dict(seen.get("gone", {}))
    for key, value in current.items():
        old = items.get(key)
        if old is None:
            # A name that left and came back within the window keeps its old first_seen.
            items[key] = {"value": value, "first": OLD if first_run else gone.pop(key, {}).get("first", stamp), "was": None}
        elif old["value"] != value:
            items[key] = {"value": value, "first": stamp, "was": old["value"]}
    for key in [k for k in items if k not in current]:
        gone[key] = {**items.pop(key), "left": stamp}
    gone = {k: v for k, v in gone.items() if is_new(v["left"], now)}
    new = {k: {"was": v["was"]} for k, v in items.items() if is_new(v["first"], now)}
    new["_gone"] = sorted(gone)
    return {"items": items, "gone": gone, "updated": stamp}, new
