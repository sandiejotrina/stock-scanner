"""Scan rules and trade plans. Pure functions: no network calls here.

Earnings dates, market caps and option chains are passed in by the caller,
which keeps these rules testable offline.
"""

from datetime import date

import numpy as np


# ---------- Bucket 1: swing breakouts ----------

def swing_checks(s: dict, rules: dict) -> dict:
    """Each rule as True/False so the report can show why a name passed or failed."""
    return {
        "above_50": s["price"] > s["sma50"],
        "above_200": s["price"] > s["sma200"],
        "50_rising": s["sma50"] > s["sma50_20ago"],
        "200_rising": s["sma200"] > s["sma200_20ago"],
        "near_high": s["price"] >= s["high50"] * (1 - rules["max_pct_below_high"]),
        "tight_base": s["bbw"] < s["bbw_avg50"] and s["base_depth"] <= rules["max_base_depth"],
        "volume_drying": s["vol10"] < s["vol50"],
        "beats_spy": s["ret63"] > s["spy_ret63"],
        "liquid": s["vol50"] >= rules["min_avg_volume"] and s["price"] >= rules["min_price"],
    }


def swing_score(s: dict) -> float:
    """Higher is better: relative strength, tightness, and closeness to the pivot."""
    rs = s["ret63"] - s["spy_ret63"]
    tightness = 1 - s["bbw"] / s["bbw_avg50"] if s["bbw_avg50"] else 0
    proximity = 1 - (s["high50"] - s["price"]) / s["high50"]
    return round(100 * (rs + 0.5 * tightness + 0.5 * proximity), 1)


def swing_plan(s: dict, account: dict, rules: dict | None = None) -> dict:
    """Buy stop just over the pivot. Stop at the tighter of: just under the base, or 2 ATR below entry.
    Targets at 2R (minimum) and 3R (stretch)."""
    rules = rules or {}
    entry = round(s["high50"] * 1.002 + 0.01, 2)
    base_stop = s["base_low"] - 0.01
    atr = s.get("atr14")
    atr_stop = entry - rules.get("atr_mult", 2.0) * atr if atr and atr == atr else base_stop
    stop = round(max(base_stop, atr_stop), 2)  # the higher stop is the tighter one
    risk = entry - stop
    dollars_at_risk = account["size"] * account["risk_per_trade_pct"]
    shares = int(dollars_at_risk // risk) if risk > 0 else 0
    max_shares = int(account["size"] * account["max_position_pct"] // entry)
    shares = min(shares, max_shares)
    return {
        "entry": entry,
        "stop": stop,
        "risk_pct": round(100 * risk / entry, 1),
        "risk_per_share": round(risk, 2),
        "target_2r": round(entry + 2 * risk, 2),
        "target_3r": round(entry + 3 * risk, 2),
        "shares": shares,
        "position_$": round(shares * entry),
        "max_loss_$": round(shares * risk),
    }


# ---------- Bucket 2: cash secured puts / covered calls ----------

def csp_checks(s: dict, rules: dict) -> dict:
    return {
        "above_200": s["price"] > s["sma200"],
        "price_range": rules["min_price"] <= s["price"] <= rules["max_price"],
        "liquid": s["vol50"] >= rules["min_avg_volume"],
    }


def support_level(s: dict, min_cushion: float = 0.03) -> float:
    """Highest real support at least min_cushion below price: 20 day low, 50 or 200 SMA."""
    ceiling = s["price"] * (1 - min_cushion)
    levels = [lvl for lvl in (s["low20"], s["sma50"], s["sma200"]) if lvl and lvl <= ceiling]
    return max(levels) if levels else s["price"] * 0.9


def days_until(d: date | None, today: date) -> int | None:
    return None if d is None else (d - today).days


def earnings_ok(earnings: date | None, today: date, min_days: int) -> bool | None:
    """None means the date is unknown, which the report flags for a manual check."""
    days = days_until(earnings, today)
    return None if days is None else days > min_days


def pick_option(chain, strike_target: float, side: str, rules: dict) -> dict | None:
    """From an option chain DataFrame, take the strike nearest the target on the safe side
    that passes liquidity rules. side='put' takes strikes at or below target, 'call' at or above."""
    if chain is None or len(chain) == 0:
        return None
    df = chain.copy()
    df = df[df["strike"] <= strike_target] if side == "put" else df[df["strike"] >= strike_target]
    if df.empty:
        return None
    df["mid"] = (df["bid"] + df["ask"]) / 2
    df = df[(df["mid"] > 0) & (df["openInterest"].fillna(0) >= rules["min_open_interest"])]
    df = df[(df["ask"] - df["bid"]) / df["mid"] <= rules["max_spread_pct"]]
    if df.empty:
        return None
    row = df.sort_values("strike", ascending=(side == "call")).iloc[0]
    return {
        "strike": float(row["strike"]),
        "bid": float(row["bid"]),
        "ask": float(row["ask"]),
        "mid": round(float(row["mid"]), 2),
        "open_interest": int(row["openInterest"]),
        "iv": float(row.get("impliedVolatility", np.nan)),
    }


def csp_plan(opt: dict, dte: int, price: float) -> dict:
    premium = opt["mid"]
    strike = opt["strike"]
    return {
        "strike": strike,
        "premium": premium,
        "credit_$": round(premium * 100),
        "cash_secured_$": round(strike * 100),
        "return_pct": round(100 * premium / strike, 2),
        "annualized_pct": round(100 * premium / strike * 365 / dte, 1),
        "breakeven": round(strike - premium, 2),
        "cushion_pct": round(100 * (price - (strike - premium)) / price, 1),
    }


def cc_plan(opt: dict, dte: int, cost_basis: float, price: float) -> dict:
    premium = opt["mid"]
    strike = opt["strike"]
    return {
        "strike": strike,
        "premium": premium,
        "credit_$": round(premium * 100),
        "annualized_pct": round(100 * premium / price * 365 / dte, 1),
        "if_called_gain_pct": round(100 * (strike + premium - cost_basis) / cost_basis, 1),
        "upside_cap_pct": round(100 * (strike - price) / price, 1),
    }
