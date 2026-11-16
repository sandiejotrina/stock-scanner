"""Buy points from the chart: where a buy would make sense, the stop, and what has to happen first.

Four kinds, checked in this order:
- No buy point: the stock is making lower highs and lower lows, or sits under a falling 200 day. Instead of a level it
  says what would change that (a higher low, then a close over the last swing high). Nothing else is offered.
- Breakout: the top of a tight base near the high, a tight 20 day range, or the box built after a big drop. It counts
  only on a close over the level on 1.5x normal volume. More than 5% over the level is extended: do not chase.
- Pullback: a stock already in an uptrend (price over a rising 50 day, 50 day over a rising 200 day). The zone runs
  from the 21 day average down to the 50 day. Volume should dry up on the way down, and the buy is a day that
  closes over the prior day's high inside the zone. Stop under the 50 day or the last 10 day low.
- Long term: where the Long term tab's buy zone overlaps real chart support (the 50 day, the 200 day, or a swing low
  from the last year). One number instead of a wide zone; it is also a natural put strike.

A buy point is a level to watch, not a buy. Pure functions, no network.
"""
from __future__ import annotations

import pandas as pd

from .indicators import atr, sma, swing_structure
from .ranges import drop_base_watch, watch_levels

CHASE = 0.05      # more than 5% over a breakout level is extended
NEAR = 0.03       # within 3% counts as near
BREAK_VOLUME = 1.5
MAX_SWING_RISK = 6.0  # the swing rule skips setups risking more than 6%


def _r(x) -> float:
    return round(float(x), 2)


def _pct(a, b) -> float:
    return round(100 * (a - b) / b, 1)


def swing_lows(df: pd.DataFrame, k: int = 10, lookback: int = 252) -> list[float]:
    d = df.tail(lookback)
    low = d["Low"].to_numpy()
    return [float(low[i]) for i in range(k, len(d) - k) if low[i] == low[i - k:i + k + 1].min()]


def no_buy_point(df: pd.DataFrame) -> dict | None:
    """Why there is no buy point, and what would change it. None when the trend allows one."""
    close = df["Close"]
    price = float(close.iloc[-1])
    s200 = sma(close, 200)
    st = swing_structure(df) or {}
    falling_200 = len(s200.dropna()) > 21 and s200.iloc[-1] < s200.iloc[-21]
    if st.get("lower_highs_lows"):
        return {"why": f"Lower highs and lower lows (high {st['high_prev']} then {st['high_last']}, "
                       f"low {st['low_prev']} then {st['low_last']}).",
                "change": f"A higher low that holds over {st['low_last']}, then a close over {st['high_last']} "
                          f"on 1.5x volume.", "level": st["high_last"]}
    if falling_200 and price < s200.iloc[-1]:
        return {"why": f"Under a falling 200 day ({_r(s200.iloc[-1])}).",
                "change": f"A close back over the 200 day ({_r(s200.iloc[-1])}) and the 200 day turning up.",
                "level": _r(s200.iloc[-1])}
    return None


def breakout_point(df: pd.DataFrame) -> dict | None:
    close, high, low, vol = df["Close"], df["High"], df["Low"], df["Volume"]
    price = float(close.iloc[-1])
    vol50 = float(vol.iloc[-51:-1].mean())  # normal volume before today
    a = float(atr(df).iloc[-1])
    source = None
    prior = df.iloc[:-1]  # the level comes from the days before today, so a breakout day cannot move its own level
    base = prior.tail(25)
    high50 = float(prior["High"].tail(50).max())
    depth = (float(base["High"].max()) - float(base["Low"].min())) / float(base["High"].max())
    if depth <= 0.15 and price >= high50 * 0.95:
        level, floor, source = high50, float(base["Low"].min()), "the top of a tight base near the high"
    elif (w := watch_levels(prior)) is not None:
        level, floor, source = w["high"], w["low"], "the top of a tight 20 day range"
    elif (w := drop_base_watch(prior)) is not None:
        level, floor = w["high"], w["low"]
        source = f"the top of the box built after the {w['drop_pct']}% drop on {w['drop_date']}"
    if source is None:
        return None
    level = _r(level)
    stop = _r(max(floor - 0.01, level - 2 * a))
    rvol = round(float(vol.iloc[-1]) / vol50, 2) if vol50 else None
    need = int(round(BREAK_VOLUME * vol50, -3))
    if price > level * (1 + CHASE):
        status, ready = f"Extended: {_pct(price, level)}% over the level. Do not chase.", False
    elif price >= level and rvol is not None and rvol >= BREAK_VOLUME:
        status, ready = f"Closed over the level on {rvol}x volume. Buy range up to {_r(level * (1 + CHASE))}.", True
    elif price >= level:
        status, ready = f"Over the level on light volume ({rvol}x). Wait for a close on 1.5x.", False
    else:
        status, ready = f"Waiting: {_pct(level, price)}% below the level.", False
    risk = round(100 * (level - stop) / level, 1)
    if risk > MAX_SWING_RISK:
        status += f" The stop is {risk}% away, wider than the 6% swing limit."
    return {"kind": "Breakout", "level": level, "zone_low": level, "zone_high": _r(level * (1 + CHASE)), "stop": stop,
            "risk_pct": round(100 * (level - stop) / level, 1), "status": status, "ready": ready,
            "distance_pct": max(_pct(level, price), 0.0) if price <= level * (1 + CHASE) else None,
            "why": f"Buy point at {source}.",
            "confirm": f"A close over {level} on {need:,}+ shares (1.5x normal).", "volume_needed": need}


def pullback_point(df: pd.DataFrame) -> dict | None:
    close, vol = df["Close"], df["Volume"]
    price = float(close.iloc[-1])
    s50, s200 = sma(close, 50), sma(close, 200)
    if len(s200.dropna()) < 21:
        return None
    up = (price > s50.iloc[-1] * 0.97 and s50.iloc[-1] > s200.iloc[-1]
          and s50.iloc[-1] > s50.iloc[-21] and s200.iloc[-1] > s200.iloc[-21])
    if not up:
        return None
    e21 = float(close.ewm(span=21, adjust=False).mean().iloc[-1])
    hi, lo = max(e21, float(s50.iloc[-1])), min(e21, float(s50.iloc[-1]))
    stop = _r(min(float(s50.iloc[-1]), float(df["Low"].tail(10).min())) * 0.99)
    drying = float(vol.tail(5).mean()) < float(vol.tail(50).mean())
    prev_high = float(df["High"].iloc[-2])
    if price > hi * 1.02:
        status, ready = f"Waiting for a pullback: {_pct(price, hi)}% over the top of the zone.", False
    elif price >= lo * 0.99:
        turned = price > prev_high
        if turned and drying:
            status, ready = "In the zone and closed over the prior day's high on quiet selling. This is the setup.", True
        elif turned:
            status, ready = "In the zone and turned up, but the pullback came on heavy volume. Smaller size or wait.", False
        else:
            status, ready = ("In the zone. " + ("Volume is drying up, good. " if drying else "Selling volume is heavy. ")
                             + f"Buy on a close over {_r(prev_high)}."), False
    else:
        status, ready = f"Under the 50 day: the pullback failed. Wait for a close back over {_r(lo)}.", False
    risk = round(100 * (hi - stop) / hi, 1)
    if risk > MAX_SWING_RISK:
        status += f" The stop is {risk}% away, wider than the 6% swing limit."
    return {"kind": "Pullback", "level": _r(hi), "zone_low": _r(lo), "zone_high": _r(hi), "stop": stop,
            "risk_pct": round(100 * (hi - stop) / hi, 1), "status": status, "ready": ready,
            "distance_pct": max(_pct(price, hi), 0.0) if price >= lo * 0.99 else None,
            "why": "Uptrend pullback: the 21 day average down to the 50 day.",
            "confirm": "A day that closes over the prior day's high inside the zone, with lighter volume on the way down.",
            "volume_drying": drying}


def longterm_point(df: pd.DataFrame, zone: dict | None) -> dict | None:
    if not zone or zone.get("low") is None or zone.get("high") is None:
        return None
    close = df["Close"]
    price = float(close.iloc[-1])
    zl, zh = float(zone["low"]), float(zone["high"])
    cands = {"the 50 day": float(sma(close, 50).iloc[-1]), "the 200 day": float(sma(close, 200).iloc[-1])}
    for i, v in enumerate(sorted(swing_lows(df), reverse=True)[:5]):
        cands[f"a swing low ({_r(v)})" if i else f"the last swing low ({_r(v)})"] = v
    inside = {k: v for k, v in cands.items() if zl <= v <= zh and v == v}
    below = {k: v for k, v in inside.items() if v <= price * 1.02}
    broke = sorted(k for k, v in inside.items() if v > price * 1.02)
    if below:
        name, point = max(below.items(), key=lambda kv: kv[1])
        why = f"The buy zone ({_r(zl)} to {_r(zh)}) meets {name}."
    else:
        name, point = "the zone bottom", zl
        why = (f"No chart support inside the buy zone ({_r(zl)} to {_r(zh)}) under the price, so the point is the "
               "zone bottom.")
    if broke:
        why += f" The price is under {', '.join(broke)}, which now acts as a ceiling."
    point = _r(point)
    if price < zl * 0.98:
        status, ready = f"Under the zone ({_pct(price, zl)}%): support broke. Wait for a close back in the zone.", False
    elif price <= point * 1.02:
        status, ready = "At the buy point.", True
    elif price <= zh * 1.02:
        status, ready = f"In the zone, {_pct(price, point)}% over the support point. A starter here, more at {point}.", True
    else:
        status, ready = f"Over the zone: {_pct(price, point)}% above the point. Wait.", False
    return {"kind": "Long term", "level": point, "zone_low": _r(zl), "zone_high": _r(zh), "stop": _r(zl * 0.95),
            "risk_pct": None, "status": status, "ready": ready, "distance_pct": max(_pct(price, point), 0.0),
            "why": why, "confirm": "Buy in pieces. Also the natural strike for a cash secured put.", "support": name}


def buy_points(df: pd.DataFrame, verdict: dict | None = None) -> dict:
    price = _r(df["Close"].iloc[-1])
    blocked = no_buy_point(df)
    if blocked:
        return {"price": price, "points": [], "none": blocked}
    pts = [p for p in (breakout_point(df), pullback_point(df), longterm_point(df, (verdict or {}).get("zone"))) if p]
    return {"price": price, "points": pts, "none": None if pts else
            {"why": "No base, no uptrend pullback and no buy zone right now.", "change": "Nothing to watch yet.",
             "level": None}}


def build(prices: dict[str, pd.DataFrame], verdicts: dict, as_of: str | None = None) -> dict:
    out = {}
    for t, df in prices.items():
        if df is None or len(df) < 220:
            continue
        try:
            out[t] = buy_points(df, verdicts.get(t))
        except Exception:  # one bad history must never stop the rest
            continue
    return {"as_of": as_of, "by_ticker": out}
