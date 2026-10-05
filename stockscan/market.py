"""Per-ticker technical status for every stock the dashboard shows."""

import numpy as np
import pandas as pd

from .indicators import pct_change, snapshot
from .scans import swing_checks


def ticker_status(df: pd.DataFrame, spy: pd.DataFrame, swing_rules: dict) -> dict:
    s = snapshot(df, spy)
    close = df["Close"]
    high_52w = float(df["High"].tail(252).max())
    checks = swing_checks(s, swing_rules)

    if s["price"] > s["sma50"] > s["sma200"] and s["sma50"] > s["sma50_20ago"]:
        trend = "uptrend"
    elif s["price"] < s["sma50"] < s["sma200"]:
        trend = "downtrend"
    else:
        trend = "mixed"

    def pct(x):
        return None if x is None or np.isnan(x) else round(100 * x, 1)

    return {
        "price": round(s["price"], 2),
        "chg_1d": pct(pct_change(close, 1)),
        "chg_1m": pct(pct_change(close, 21)),
        "chg_3m": pct(pct_change(close, 63)),
        "chg_1y": pct(pct_change(close, 252)),
        "vs_spy_3m": pct(s["ret63"] - s["spy_ret63"]),
        "from_52w_high": pct(s["price"] / high_52w - 1),
        "above_50": bool(checks["above_50"]),
        "above_200": bool(checks["above_200"]),
        "trend": trend,
        "breakout_setup": bool(all(checks.values())),
        "hv20": pct(s["hv20"]),
        # Last 6 months of closes, weekly, for a sparkline.
        "spark": [round(float(v), 2) for v in close.tail(126).iloc[::5]],
    }


def market_status(prices: dict, spy: pd.DataFrame, swing_rules: dict) -> dict:
    out = {}
    for t, df in prices.items():
        try:
            out[t] = ticker_status(df, spy, swing_rules)
        except (IndexError, KeyError, ZeroDivisionError):
            continue
    return out
