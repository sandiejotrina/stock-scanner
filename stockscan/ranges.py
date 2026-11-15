"""Range breaks in both directions: stocks moving out of a tight range, up or down, and the volume behind the move.

A range is the high and low of the last 20 sessions, counted only when it is tight: the range is no deeper than 12% of
its high and the Bollinger width is under its 50 day average (a squeeze). A break is a CLOSE past the range high or
low. It counts as confirmed only on at least 1.5 times the 50 day average volume, the same bar as the swing rule.

Two outputs:
- breaks: names that closed out of a tight range in the last 3 sessions, with the volume ratio.
- watch: names still inside a tight range, ranked by how close they sit to an edge. The phone alerts go at those edges.

A break down is a warning, not a short. It says: do not sell puts here, and do not buy for the long term yet.
Pure functions, no network.
"""
from __future__ import annotations

import pandas as pd

from .indicators import bollinger_width

DEFAULTS = {"range_days": 20, "max_range_depth": 0.12, "break_volume": 1.5, "recent_sessions": 3,
            "max_per_side": 10, "min_avg_volume": 500000, "min_price": 15}


def _rules(rules: dict | None) -> dict:
    return {**DEFAULTS, **(rules or {})}


def _range(df: pd.DataFrame, end: int, bbw: pd.Series, r: dict) -> dict | None:
    """The range over the `range_days` bars before position `end` (not including it). None when it is not tight."""
    n = r["range_days"]
    if end - n < 50:
        return None
    win = df.iloc[end - n:end]
    hi, lo = float(win["High"].max()), float(win["Low"].min())
    depth = (hi - lo) / hi if hi else 1.0
    w = bbw.iloc[:end]
    squeeze = bool(w.iloc[-1] < w.tail(50).mean())
    if depth > r["max_range_depth"] or not squeeze:
        return None
    return {"high": round(hi, 2), "low": round(lo, 2), "depth_pct": round(100 * depth, 1)}


def _liquid(df: pd.DataFrame, r: dict) -> bool:
    return float(df["Volume"].tail(50).mean()) >= r["min_avg_volume"] and float(df["Close"].iloc[-1]) >= r["min_price"]


def find_break(df: pd.DataFrame, rules: dict | None = None) -> dict | None:
    """The first close out of a tight range within the last `recent_sessions` bars, or None."""
    r = _rules(rules)
    bbw = bollinger_width(df["Close"])
    size = len(df)
    for i in range(size - r["recent_sessions"], size):
        rng = _range(df, i, bbw, r)
        if rng is None:
            continue
        close = float(df["Close"].iloc[i])
        side = "up" if close > rng["high"] else "down" if close < rng["low"] else None
        if side is None:
            continue
        avg = float(df["Volume"].iloc[i - 50:i].mean())
        rvol = round(float(df["Volume"].iloc[i]) / avg, 2) if avg else None
        level = rng["high"] if side == "up" else rng["low"]
        last = float(df["Close"].iloc[-1])
        holding = last > level if side == "up" else last < level
        confirmed = rvol is not None and rvol >= r["break_volume"]
        return {"side": side, "level": level, "range_high": rng["high"], "range_low": rng["low"],
                "depth_pct": rng["depth_pct"], "date": df.index[i].date().isoformat(), "days_ago": size - 1 - i,
                "close": round(close, 2), "price": round(last, 2), "rvol": rvol, "confirmed": bool(confirmed),
                "holding": bool(holding), "note": break_note(side, confirmed, holding, rvol, r)}
    return None


def break_note(side: str, confirmed: bool, holding: bool, rvol, r: dict) -> str:
    vol = f"{rvol}x normal volume" if rvol is not None else "unknown volume"
    if not holding:
        return f"Broke {side} on {vol} but closed back inside the range. Failed break, ignore it."
    if side == "up":
        return (f"Closed over the range on {vol}. Confirmed. Check the chart before any entry." if confirmed
                else f"Closed over the range on light volume ({vol}). Weak, wait for volume.")
    return (f"Closed under the range on {vol}. Confirmed. Do not sell puts here, and wait before any long term buy."
            if confirmed else f"Closed under the range on light volume ({vol}). A warning, not yet confirmed.")


def watch_levels(df: pd.DataFrame, rules: dict | None = None) -> dict | None:
    """The current tight range (the last `range_days` bars, today included), or None."""
    r = _rules(rules)
    bbw = bollinger_width(df["Close"])
    rng = _range(df, len(df), bbw, r)
    if rng is None:
        return None
    price = float(df["Close"].iloc[-1])
    vol50 = float(df["Volume"].tail(50).mean())
    return {**rng, "price": round(price, 2), "to_high_pct": round(100 * (rng["high"] - price) / price, 1),
            "to_low_pct": round(100 * (price - rng["low"]) / price, 1),
            "volume_needed": int(round(r["break_volume"] * vol50, -3))}


def scan_ranges(prices: dict[str, pd.DataFrame], rules: dict | None = None, as_of: str | None = None) -> dict:
    """Breaks in the last few sessions plus the closest names to each edge of a tight range."""
    r = _rules(rules)
    up, down, inside = [], [], []
    for t, df in prices.items():
        if df is None or len(df) < r["range_days"] + 60 or not _liquid(df, r):
            continue
        b = find_break(df, r)
        if b:
            (up if b["side"] == "up" else down).append({"ticker": t, **b})
            continue
        w = watch_levels(df, r)
        if w:
            inside.append({"ticker": t, **w})
    order = lambda x: (not x["holding"], not x["confirmed"], -(x["rvol"] or 0))
    up.sort(key=order)
    down.sort(key=order)
    cap = r["max_per_side"]
    watch_up = sorted(inside, key=lambda x: x["to_high_pct"])[:cap]
    watch_down = sorted(inside, key=lambda x: x["to_low_pct"])[:cap]
    return {"as_of": as_of, "rules": {k: r[k] for k in ("range_days", "max_range_depth", "break_volume", "recent_sessions")},
            "breaks_up": up[:15], "breaks_down": down[:15], "watch_up": watch_up, "watch_down": watch_down}
