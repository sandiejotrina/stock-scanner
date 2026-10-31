"""Verdict engine: quality checks, fair value and the four verdicts."""

from stockscan.valuation import chart_ready, fair_value, quality, verdict

GOOD = {"revenue_growth": 0.20, "earnings_growth": 0.25, "operating_margin": 0.30, "gross_margin": 0.60,
        "fcf": 5e9, "total_debt": 1e9, "ebitda": 8e9, "forward_eps": 5.0}
# Fair P/E = 1.5 x 20% growth (the lower of 20% and 25%) = 30, so fair value is 150 (range 127.5 to 172.5).


def mkt(price, s50, s200, trend="uptrend"):
    return {"price": price, "sma50": s50, "sma200": s200, "trend": trend}


def test_quality_counts_known_checks():
    q = quality(GOOD)
    assert q["passed"] == 5 and q["known"] == 5
    weak = quality({"revenue_growth": -0.05, "operating_margin": 0.02, "fcf": -1e8})
    assert weak["passed"] == 0 and weak["known"] == 3


def test_fair_value_profitable_and_premium():
    base, prem = fair_value(GOOD, False), fair_value(GOOD, True)
    assert base["mid"] == 150 and base["stage"] == "profitable"
    assert round(prem["mid"] / base["mid"], 2) == 1.2


def test_fair_value_early_stage_uses_sales():
    f = {"forward_eps": -1, "revenue": 1e9, "shares": 1e8, "revenue_growth": 0.40, "gross_margin": 0.7,
         "total_cash": 5e8, "total_debt": 0}
    fv = fair_value(f, False)
    assert fv["stage"] == "early" and fv["mid"] == round((10 * 1.2 * 1e9 + 5e8) / 1e8, 2)


def test_buy_zone_now_when_price_sits_on_support_inside_fair_value():
    v = verdict("X", GOOD, mkt(150, 148, 135), premium=False)
    assert v["verdict"] == "Buy zone now"
    assert v["zone"]["low"] <= 150 <= v["zone"]["high"] * 1.02


def test_accumulate_when_extended_above_the_50_day():
    v = verdict("X", GOOD, mkt(168, 150, 135), premium=False)
    assert v["verdict"] == "Accumulate on pullback"


def test_wait_when_far_above_fair_value_or_in_downtrend():
    assert verdict("X", GOOD, mkt(300, 290, 250), premium=False)["verdict"] == "Wait"
    assert verdict("X", GOOD, mkt(150, 160, 170, "downtrend"), premium=False)["verdict"] == "Wait"


def test_avoid_when_quality_fails_and_no_data_when_missing():
    bad = {"revenue_growth": -0.1, "earnings_growth": -0.2, "operating_margin": 0.01, "fcf": -1e9, "forward_eps": 1.0}
    assert verdict("X", bad, mkt(20, 20, 20), premium=False)["verdict"] == "Avoid"
    assert verdict("X", {}, mkt(20, 20, 20), premium=False)["verdict"] == "Not enough data"


def test_undervalued_stock_on_support_is_a_buy_not_accumulate():
    # Fair value about 128 to 173, but the stock trades at 100 right on its averages.
    v = verdict("X", GOOD, mkt(100, 98, 92), premium=False)
    assert v["verdict"] == "Buy zone now" and v["zone"]["low"] < 100 < v["zone"]["high"]
    assert "below fair value" in v["reasons"][0]


def test_barely_profitable_company_is_valued_on_sales():
    f = {**GOOD, "forward_eps": 0.05, "revenue": 1e9, "shares": 1e8, "revenue_growth": 0.4, "gross_margin": 0.3}
    assert fair_value({**f, "price": 70}, False)["stage"] == "early"


def test_penny_stocks_never_get_a_buy():
    assert verdict("X", {**GOOD, "forward_eps": 0.1}, mkt(2.7, 2.7, 2.6), premium=False)["verdict"] == "Wait"


def test_no_verdict_when_earnings_and_price_do_not_line_up():
    v = verdict("X", {**GOOD, "financial_currency": "EUR", "currency": "USD"}, mkt(150, 148, 135), premium=False)
    assert v["verdict"] == "Not enough data"
    v = verdict("X", GOOD, mkt(20, 20, 19), premium=False)  # fair value about 150 vs price 20
    assert v["verdict"] == "Not enough data"


def test_price_below_support_is_wait_not_accumulate():
    v = verdict("X", GOOD, mkt(120, 140, 135, "mixed"), premium=False)
    assert v["verdict"] == "Wait"


def test_buy_zone_needs_a_ready_chart():
    from stockscan.valuation import chart_ready
    m = mkt(150, 148, 135)
    ok = verdict("X", GOOD, {**m, "up_down_vol": 1.3, "chg_1m": 2.0, "sma200_rising": True}, premium=False)
    assert ok["verdict"] == "Buy zone now" and ok["chart"]["ready"]
    bad = verdict("X", GOOD, {**m, "up_down_vol": 0.7, "chg_1m": -12.0, "sma200_rising": True}, premium=False)
    assert bad["verdict"] == "Buy zone, wait for the chart"
    assert len(bad["chart"]["failed"]) == 2
    # The reason must name what is wrong, not repeat the passing condition.
    assert "sellers outweigh buyers" in bad["reasons"][0] and "buyers outweigh sellers" not in bad["reasons"][0]
    assert "sliding (down 8% or more" in bad["reasons"][0]
    assert chart_ready({"price": 10, "trend": "uptrend"})["ready"]  # unknown checks do not block


def test_chart_checks_with_numpy_numbers():
    """CI passes numpy floats. A failed check must still block the buy and save as a real false."""
    import json
    import numpy as np
    r = chart_ready({"price": 10.0, "trend": "mixed", "chg_1m": np.float64(-8.8), "up_down_vol": np.float64(1.1)})
    assert not r["ready"] and r["failed"] == ["Not sliding (down less than 8% in a month)"]
    assert '"False"' not in json.dumps(r, default=str)


def _chart(highs_lows):
    """Daily bars that walk through the given (high, low) turning points in straight lines, 15 days apart."""
    import numpy as np
    import pandas as pd
    pts = []
    for (a_h, a_l), (b_h, b_l) in zip(highs_lows, highs_lows[1:]):
        pts += list(zip(np.linspace(a_h, b_h, 15, endpoint=False), np.linspace(a_l, b_l, 15, endpoint=False)))
    pts += [highs_lows[-1]] * 3
    hi, lo = np.array([p[0] for p in pts]), np.array([p[1] for p in pts])
    close = (hi + lo) / 2
    return pd.DataFrame({"Open": close, "High": hi, "Low": lo, "Close": close, "Volume": 1e6},
                        index=pd.bdate_range("2026-01-01", periods=len(pts)))


def test_swing_structure_catches_lower_highs_and_lower_lows():
    from stockscan.indicators import swing_structure
    # PWR's shape in 2026: highs 742, 725, 722 and lows 594 then 527, bouncing to 623.
    falling = _chart([(700, 680), (742, 720), (650, 600), (725, 700), (620, 594), (722, 700), (560, 527), (630, 615)])
    s = swing_structure(falling)
    assert s["lower_highs_lows"] is True and s["low_last"] < s["low_prev"] and s["high_last"] < s["high_prev"]
    rising = _chart([(600, 580), (650, 630), (610, 590), (680, 660), (640, 620), (710, 690), (670, 650), (700, 685)])
    assert swing_structure(rising)["lower_highs_lows"] is False


def test_lower_highs_and_lows_fail_the_chart_and_drop_the_put_hint():
    m = {**mkt(150, 148, 135), "up_down_vol": 1.2, "chg_1m": 1.0, "sma200_rising": True,
         "structure": {"lower_highs_lows": True}}
    assert chart_ready(m)["failed"] == ["No lower highs and lower lows"]
    v = verdict("X", GOOD, m, premium=False)
    assert v["verdict"] == "Buy zone, wait for the chart"
    assert "lower highs and lower lows" in v["reasons"][0] and "sell a cash secured put" not in v["reasons"][0]
    ok = verdict("X", GOOD, {**m, "structure": {"lower_highs_lows": False}}, premium=False)
    assert ok["verdict"] == "Buy zone now"
