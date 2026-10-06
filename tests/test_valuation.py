"""Verdict engine: quality checks, fair value and the four verdicts."""

from stockscan.valuation import fair_value, quality, verdict

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
