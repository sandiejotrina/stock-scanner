import numpy as np
import pandas as pd

from stockscan.buypoints import breakout_point, buy_points, longterm_point, no_buy_point, pullback_point


def frame(closes, volumes=None, spread=0.5):
    idx = pd.bdate_range("2025-01-01", periods=len(closes))
    c = np.array(closes, dtype=float)
    v = np.array(volumes if volumes is not None else [1_000_000] * len(c), dtype=float)
    return pd.DataFrame({"Open": c, "High": c + spread, "Low": c - spread, "Close": c, "Volume": v}, index=idx)


def uptrend(n=260, slope=0.15, wiggle=1.0):
    return [50 + slope * i + wiggle * np.sin(i / 3) for i in range(n)]


def downtrend():
    # clear swings: peaks falling, troughs falling
    return [200 - 0.3 * i + 12 * np.sin(i / 8) for i in range(300)]


def test_downtrend_gets_no_buy_point_and_says_what_would_change_it():
    bp = buy_points(frame(downtrend()), {"zone": {"low": 90, "high": 120}})
    assert bp["points"] == []
    assert bp["none"]["level"] is not None
    assert "close over" in bp["none"]["change"] or "200 day" in bp["none"]["change"]


def test_uptrend_pullback_into_the_zone():
    closes = uptrend()
    closes += [closes[-1] - 0.8 * k for k in range(1, 5)]  # pull back toward the 21 day
    vols = [1_000_000] * (len(closes) - 5) + [600_000] * 5  # quiet selling
    p = pullback_point(frame(closes, vols))
    assert p and p["kind"] == "Pullback" and p["zone_low"] <= p["zone_high"]
    assert p["volume_drying"] and p["stop"] < p["zone_low"]


def test_no_pullback_point_when_not_in_an_uptrend():
    assert pullback_point(frame([100.0] * 260)) is None


def test_breakout_waits_then_confirms_on_volume():
    closes = uptrend(240) + [86 + 0.4 * np.sin(i) for i in range(25)]
    df = frame(closes)
    p = breakout_point(df)
    assert p and p["kind"] == "Breakout" and "Waiting" in p["status"] and not p["ready"]
    over = frame(closes + [p["level"] + 0.6], [1_000_000] * len(closes) + [2_000_000])
    q = breakout_point(over)
    assert q["ready"] and "Buy range up to" in q["status"]
    light = frame(closes + [p["level"] + 0.6])
    assert "light volume" in breakout_point(light)["status"]


def test_breakout_extended_means_do_not_chase():
    closes = uptrend(240) + [86 + 0.4 * np.sin(i) for i in range(25)]
    level = breakout_point(frame(closes))["level"]
    p = breakout_point(frame(closes + [level * 1.08], [1_000_000] * len(closes) + [3_000_000]))
    assert p is None or "Do not chase" in p["status"] or p["level"] != level


def test_long_term_point_uses_support_under_the_price():
    df = frame(uptrend())
    price = float(df["Close"].iloc[-1])
    p = longterm_point(df, {"low": price * 0.85, "high": price * 1.01})
    assert p["level"] <= price * 1.02 and p["zone_low"] <= p["level"] <= p["zone_high"]
    assert p["ready"]


def test_long_term_point_under_the_zone_is_not_ready():
    df = frame(uptrend())
    price = float(df["Close"].iloc[-1])
    p = longterm_point(df, {"low": price * 1.1, "high": price * 1.2})
    assert not p["ready"] and "Under the zone" in p["status"]


def test_long_term_point_needs_a_zone():
    assert longterm_point(frame(uptrend()), None) is None
    assert no_buy_point(frame(uptrend())) is None


def test_buyout_pending_gets_no_buy_point():
    bp = buy_points(frame(uptrend()), {"verdict": "Buyout pending", "zone": {"low": 60, "high": 100}})
    assert bp["points"] == [] and "buyout" in bp["none"]["why"].lower()
