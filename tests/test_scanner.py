import pytest
"""Offline tests on synthetic prices. Run with: python -m pytest tests"""

from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from stockscan.runner import (
    load_settings, load_universe, run_covered_calls, run_csp, run_long_term,
    run_swing, write_report,
)
from stockscan.scans import support_level

TODAY = date(2026, 10, 5)
CFG = load_settings()


def frame(closes, volumes, spread=0.01):
    closes = np.asarray(closes, dtype=float)
    idx = pd.bdate_range(end=TODAY, periods=len(closes))
    return pd.DataFrame({
        "Open": closes, "High": closes * (1 + spread), "Low": closes * (1 - spread),
        "Close": closes, "Volume": np.asarray(volumes, dtype=float),
    }, index=idx)


def breakout_stock():
    """Steady climb, then a tight 25 day flag just under the high on light volume."""
    rng = np.random.default_rng(1)
    trend = np.linspace(50, 100, 375) * (1 + rng.normal(0, 0.01, 375))
    flag = 100 + rng.normal(0, 0.4, 25)
    vol = np.r_[np.full(375, 3e6), np.full(25, 1.5e6)]
    return frame(np.r_[trend, flag], vol, spread=0.005)


def downtrend_stock():
    rng = np.random.default_rng(2)
    return frame(np.linspace(120, 60, 400) * (1 + rng.normal(0, 0.01, 400)), np.full(400, 3e6))


def spy():
    return frame(np.linspace(400, 440, 400), np.full(400, 5e7))


class FakeSource:
    def __init__(self, earnings_days=60):
        self.earnings_days = earnings_days

    def company_events(self, ticker):
        return {"earnings": TODAY + timedelta(days=self.earnings_days),
                "ex_dividend": None, "market_cap": 5e11}

    def option_chain(self, ticker, min_dte, max_dte, today):
        strikes = np.arange(60, 141, 5.0)
        def side(kind):
            otm = (100 - strikes) if kind == "put" else (strikes - 100)
            mid = np.clip(4 - 0.15 * otm, 0.2, None)
            return pd.DataFrame({"strike": strikes, "bid": mid * 0.97, "ask": mid * 1.03,
                                 "openInterest": 500, "impliedVolatility": 0.45})
        return {"expiration": (today + timedelta(days=35)).isoformat(), "dte": 35,
                "puts": side("put"), "calls": side("call")}

    def fundamentals(self, ticker):
        return {"name": ticker, "market_cap": 1e12, "revenue_growth": 0.3, "earnings_growth": 0.4,
                "gross_margin": 0.7, "operating_margin": 0.4, "fcf": 5e10,
                "debt_to_equity": 40, "forward_pe": 30, "peg": 1.2}


PRICES = {"BRK": breakout_stock(), "DOWN": downtrend_stock()}


def test_universe_parses_multiple_tickers_per_line():
    tickers = load_universe()
    assert len(tickers) > 200 and "NVDA" in tickers and "#" not in "".join(tickers)


def test_swing_finds_breakout_and_skips_downtrend():
    df = run_swing(PRICES, spy(), CFG, FakeSource(), TODAY)
    assert list(df["ticker"]) == ["BRK"]
    row = df.iloc[0]
    assert row["entry"] > row["price"] > row["stop"]
    assert row["risk_pct"] <= 100 * CFG["swing"]["max_risk_pct"]
    assert row["target_2r"] - row["entry"] == pytest.approx(2 * (row["entry"] - row["stop"]), abs=0.02)
    # A stop out should lose about 1% of the account, never more.
    assert row["max_loss_$"] <= CFG["account"]["size"] * CFG["account"]["risk_per_trade_pct"]


def test_swing_drops_names_with_earnings_too_close():
    df = run_swing(PRICES, spy(), CFG, FakeSource(earnings_days=5), TODAY)
    assert df.empty


def test_csp_strike_sits_at_or_below_support():
    df = run_csp(PRICES, CFG, FakeSource(), TODAY)
    assert list(df["ticker"]) == ["BRK"]
    row = df.iloc[0]
    assert row["strike"] <= row["support"] < row["price"]
    assert row["breakeven"] < row["strike"]
    assert row["annualized_pct"] > 0


def test_csp_skips_when_earnings_land_before_expiration():
    assert run_csp(PRICES, CFG, FakeSource(earnings_days=20), TODAY).empty


def test_support_level_ignores_levels_above_price():
    s = {"price": 100, "low20": 96, "sma50": 102, "sma200": 85}
    assert support_level(s) == 96


def test_covered_call_strike_not_below_cost_basis():
    cfg = {**CFG, "holdings": [{"ticker": "BRK", "shares": 200, "cost_basis": 110}]}
    df = run_covered_calls(PRICES, cfg, FakeSource(), TODAY)
    assert df.iloc[0]["strike"] >= 110 and df.iloc[0]["contracts"] == 2


def test_report_writes_all_sections(tmp_path: Path):
    src = FakeSource()
    swing = run_swing(PRICES, spy(), CFG, src, TODAY)
    csp = run_csp(PRICES, CFG, src, TODAY)
    lt = run_long_term({"AI": ["NVDA"]}, src)
    path = write_report(TODAY, swing, csp, pd.DataFrame(), lt, tmp_path)
    text = path.read_text()
    for heading in ("Swing breakouts", "Cash secured puts", "Covered calls", "Long term"):
        assert heading in text
    assert "BRK" in text and "NVDA" in text


def test_loose_setups_are_skipped():
    cfg = {**CFG, "swing": {**CFG["swing"], "max_risk_pct": 0.001}}
    assert run_swing(PRICES, spy(), cfg, FakeSource(), TODAY).empty


def test_stop_uses_the_tighter_of_base_and_atr():
    from stockscan.scans import swing_plan
    acct = CFG["account"]
    s = {"high50": 100, "base_low": 90, "atr14": 2}
    plan = swing_plan(s, acct, {"atr_mult": 2})
    assert plan["stop"] == round(100 * 1.002 + 0.01 - 4, 2)  # ATR stop (about 96) beats base stop (90)
    s = {"high50": 100, "base_low": 97, "atr14": 2}
    assert swing_plan(s, acct, {"atr_mult": 2})["stop"] == 96.99  # base stop is tighter here
