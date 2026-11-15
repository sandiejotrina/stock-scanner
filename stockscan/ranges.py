"""Range breaks in both directions: stocks moving out of a tight range, up or down, and the volume behind the move.

A range is the high and low of the last 20 sessions, counted only when it is tight: the range is no deeper than 12% of
its high and the Bollinger width is under its 50 day average (a squeeze). A break is a CLOSE past the range high or
low. It counts as confirmed only on at least 1.5 times the 50 day average volume, the same bar as the swing rule.

Two outputs:
- breaks: names that closed out of a tight range in the last 3 sessions, with the volume ratio.
- watch: names still inside a tight range, ranked by how close they sit to an edge. The phone alerts go at those edges.

A break down is a warning, not a short. It says: do not sell puts here, and do not buy for the long term yet.

Bases after a drop (added 2026-11-15): a stock that fell 8% or more in one session never looks quiet to the range
test, because the crash day stays in the window (GOOGL after Oct 29, TSM after Nov 5). So a second scan finds the box
the stock builds AFTER the drop (at least 5 sessions, no deeper than 15%), with no squeeze test. A close out of that
box counts on the same 1.5x volume, measured against normal volume with the crash day left out. Every hit says
whether it is a bounce inside a downtrend.
Pure functions, no network.
"""
from __future__ import annotations

import pandas as pd

from .indicators import bollinger_width, sma, swing_structure

DEFAULTS = {"range_days": 20, "max_range_depth": 0.12, "break_volume": 1.5, "recent_sessions": 3,
            "max_per_side": 10, "min_avg_volume": 500000, "min_price": 15,
            "drop_pct": 0.08, "drop_lookback": 30, "min_base_days": 5, "max_base_depth": 0.15, "max_bases": 150}


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


# ---------- Bases after a big drop ----------

def _shock(df: pd.DataFrame, end: int, r: dict) -> int | None:
    """Position of the most recent one day drop of drop_pct or more that leaves at least min_base_days bars
    before position `end`, within drop_lookback sessions."""
    ret = df["Close"].pct_change()
    last = end - 1 - r["min_base_days"]
    for i in range(last, max(end - r["drop_lookback"], 51) - 1, -1):
        if ret.iloc[i] <= -r["drop_pct"]:
            return i
    return None


def drop_base(df: pd.DataFrame, end: int, rules: dict | None = None) -> dict | None:
    """The box built after the latest big drop, from the day after the drop up to (not including) position `end`."""
    r = _rules(rules)
    s = _shock(df, end, r)
    if s is None:
        return None
    box = df.iloc[s + 1:end]
    hi, lo = float(box["High"].max()), float(box["Low"].min())
    depth = (hi - lo) / hi if hi else 1.0
    if depth > r["max_base_depth"]:
        return None
    drop = float(df["Close"].iloc[s] / df["Close"].iloc[s - 1] - 1)
    return {"high": round(hi, 2), "low": round(lo, 2), "depth_pct": round(100 * depth, 1), "shock": s,
            "drop_date": df.index[s].date().isoformat(), "drop_pct": round(100 * drop, 1), "base_days": len(box)}


def _normal_volume(df: pd.DataFrame, i: int, shock: int) -> float:
    """50 day average volume before position i, with the crash day left out so it does not inflate normal."""
    v = df["Volume"].iloc[i - 50:i]
    return float(v.drop(df.index[shock], errors="ignore").mean())


def downtrend_note(df: pd.DataFrame) -> str | None:
    price = float(df["Close"].iloc[-1])
    s200 = float(sma(df["Close"], 200).iloc[-1]) if len(df) >= 200 else None
    st = swing_structure(df) or {}
    parts = []
    if st.get("lower_highs_lows"):
        parts.append("lower highs and lower lows")
    if s200 and price < s200:
        parts.append("under the 200 day")
    return "Bounce inside a downtrend (" + ", ".join(parts) + ")" if parts else None


def find_drop_break(df: pd.DataFrame, rules: dict | None = None) -> dict | None:
    """The first close out of a post-drop box within the last recent_sessions bars, or None."""
    r = _rules(rules)
    size = len(df)
    for i in range(size - r["recent_sessions"], size):
        b = drop_base(df, i, r)
        if b is None:
            continue
        close = float(df["Close"].iloc[i])
        side = "up" if close > b["high"] else "down" if close < b["low"] else None
        if side is None:
            continue
        avg = _normal_volume(df, i, b["shock"])
        rvol = round(float(df["Volume"].iloc[i]) / avg, 2) if avg else None
        level = b["high"] if side == "up" else b["low"]
        last = float(df["Close"].iloc[-1])
        holding = last > level if side == "up" else last < level
        confirmed = rvol is not None and rvol >= r["break_volume"]
        out = {k: v for k, v in b.items() if k != "shock"}
        return {"side": side, "level": level, "range_high": b["high"], "range_low": b["low"], **out,
                "date": df.index[i].date().isoformat(), "days_ago": size - 1 - i, "close": round(close, 2),
                "price": round(last, 2), "rvol": rvol, "confirmed": bool(confirmed), "holding": bool(holding),
                "note": break_note(side, confirmed, holding, rvol, r), "context": downtrend_note(df)}
    return None


def drop_base_watch(df: pd.DataFrame, rules: dict | None = None) -> dict | None:
    """The box a stock is building right now after a big drop (today included), or None."""
    r = _rules(rules)
    b = drop_base(df, len(df), r)
    if b is None:
        return None
    price = float(df["Close"].iloc[-1])
    normal = _normal_volume(df, len(df), b["shock"])
    return {**{k: v for k, v in b.items() if k != "shock"}, "price": round(price, 2),
            "to_high_pct": round(100 * (b["high"] - price) / price, 1),
            "to_low_pct": round(100 * (price - b["low"]) / price, 1),
            "volume_needed": int(round(r["break_volume"] * normal, -3)), "context": downtrend_note(df)}


def scan_ranges(prices: dict[str, pd.DataFrame], rules: dict | None = None, as_of: str | None = None) -> dict:
    """Breaks in the last few sessions plus the closest names to each edge of a tight range."""
    r = _rules(rules)
    up, down, inside = [], [], []
    d_up, d_down, bases = [], [], []
    for t, df in prices.items():
        if df is None or len(df) < r["range_days"] + 60 or not _liquid(df, r):
            continue
        db = find_drop_break(df, r)
        if db:
            (d_up if db["side"] == "up" else d_down).append({"ticker": t, **db})
        elif dw := drop_base_watch(df, r):
            bases.append({"ticker": t, **dw})
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
            "breaks_up": up[:15], "breaks_down": down[:15], "watch_up": watch_up, "watch_down": watch_down,
            "after_drop": {"breaks_up": sorted(d_up, key=order)[:15], "breaks_down": sorted(d_down, key=order)[:15],
                           "bases": sorted(bases, key=lambda x: min(x["to_high_pct"], x["to_low_pct"]))[:r["max_bases"]]}}
