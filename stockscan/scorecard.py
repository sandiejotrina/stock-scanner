"""Scorecard: did the dashboard's calls work?

Every call is logged once, the first day it appears, with the numbers at that moment:
- swing: a breakout setup (entry, stop, 2R target)
- put: a cash secured put, from the scanner or the brief (strike, expiry, premium)
- long: a long term "Buy zone now" verdict (price)
- signal: a brief signal's bullish and bearish tickers (price)
Each full refresh grades the open calls against real prices. Nothing is ever deleted or re-graded with
hindsight, so the record shows the bad calls too.
"""
from __future__ import annotations

from datetime import date

import pandas as pd

SWING_WINDOW = 20         # trading days for a setup to trigger
LONG_HORIZONS = (5, 20, 60)
SIGNAL_HORIZONS = (5, 20)


def _key(c: dict) -> str:
    return f"{c['type']}|{c['ticker']}|{c.get('side', '')}"


def log_calls(log: list[dict], new: list[dict]) -> list[dict]:
    """Add calls that are not already open. A call that finished can be logged again later as a new call."""
    open_keys = {_key(c) for c in log if c.get("status") in (None, "open", "waiting")}
    for c in new:
        if _key(c) not in open_keys:
            log.append({**c, "status": "open" if c["type"] != "swing" else "waiting"})
            open_keys.add(_key(c))
    return log


def _after(df: pd.DataFrame, day: str) -> pd.DataFrame:
    return df[df.index > pd.Timestamp(day)]


def _close_on(df: pd.DataFrame, day: str):
    s = df[df.index <= pd.Timestamp(day)]["Close"]
    return float(s.iloc[-1]) if len(s) else None


def grade_swing(c: dict, df: pd.DataFrame) -> dict:
    bars = _after(df, c["date"])
    risk = c["entry"] - c["stop"]
    if risk <= 0:
        return {**c, "status": "skipped", "note": "bad levels"}
    trig = None
    for i, (ts, b) in enumerate(bars.iterrows()):
        if trig is None:
            if i >= SWING_WINDOW:
                return {**c, "status": "never_triggered", "result_r": 0.0}
            if b["High"] >= c["entry"]:
                trig = ts
        if trig is not None:
            if b["Low"] <= c["stop"]:  # if both on one day, assume the stop hit first
                return {**c, "status": "loss", "result_r": -1.0, "closed": str(ts.date())}
            if b["High"] >= c["target_2r"]:
                return {**c, "status": "win", "result_r": 2.0, "closed": str(ts.date())}
    if trig is None:
        return {**c, "status": "waiting"}
    last = float(bars["Close"].iloc[-1])
    return {**c, "status": "open", "triggered": str(trig.date()), "result_r": round((last - c["entry"]) / risk, 2)}


def grade_put(c: dict, df: pd.DataFrame, today: date) -> dict:
    strike, prem = c["strike"], c.get("premium") or 0
    if today.isoformat() <= c["expiration"]:
        last = _close_on(df, today.isoformat())
        return {**c, "status": "open", "cushion_pct": round(100 * (last / strike - 1), 1) if last else None}
    close = _close_on(df, c["expiration"])
    if close is None:
        return {**c, "status": "no_data"}
    if close >= strike:
        return {**c, "status": "win", "result_pct": round(100 * prem / strike, 2), "close_at_expiry": round(close, 2)}
    return {**c, "status": "assigned", "close_at_expiry": round(close, 2),
            "result_pct": round(100 * (close - strike + prem) / strike, 2)}


def _ret(df: pd.DataFrame, day: str, n: int):
    start = _close_on(df, day)
    bars = _after(df, day)
    if start is None or len(bars) < n:
        return None
    return round(100 * (float(bars["Close"].iloc[n - 1]) / start - 1), 2)


def grade_horizons(c: dict, df: pd.DataFrame, spy: pd.DataFrame, horizons) -> dict:
    out = dict(c)
    done = True
    for n in horizons:
        r, s = _ret(df, c["date"], n), _ret(spy, c["date"], n)
        if r is None or s is None:
            done = False
            continue
        edge = r - s if c.get("side", "bullish") != "bearish" else s - r
        out[f"ret_{n}d"], out[f"vs_spy_{n}d"] = r, round(edge, 2)
    out["status"] = "done" if done else "open"
    return out


def grade(log: list[dict], prices: dict, spy: pd.DataFrame | None, today: date) -> list[dict]:
    out = []
    for c in log:
        df = prices.get(c["ticker"])
        if c.get("status") not in ("open", "waiting") or df is None or len(df) == 0:
            out.append(c)
            continue
        if c["type"] == "swing":
            out.append(grade_swing(c, df))
        elif c["type"] == "put":
            out.append(grade_put(c, df, today))
        elif spy is not None:
            out.append(grade_horizons(c, df, spy, LONG_HORIZONS if c["type"] == "long" else SIGNAL_HORIZONS))
        else:
            out.append(c)
    return out


def summary(log: list[dict]) -> dict:
    """Plain numbers per kind of call. Only finished calls count toward hit rates."""
    def avg(xs):
        xs = [x for x in xs if x is not None]
        return round(sum(xs) / len(xs), 2) if xs else None
    sw = [c for c in log if c["type"] == "swing"]
    sw_done = [c for c in sw if c["status"] in ("win", "loss")]
    pu = [c for c in log if c["type"] == "put"]
    pu_done = [c for c in pu if c["status"] in ("win", "assigned")]
    lg = [c for c in log if c["type"] == "long"]
    sg = [c for c in log if c["type"] == "signal"]
    return {
        "swing": {"calls": len(sw), "finished": len(sw_done), "wins": sum(c["status"] == "win" for c in sw_done),
                  "never_triggered": sum(c["status"] == "never_triggered" for c in sw),
                  "open": sum(c["status"] == "open" for c in sw),
                  "avg_r": avg([c.get("result_r") for c in sw_done])},
        "put": {"calls": len(pu), "finished": len(pu_done), "kept_premium": sum(c["status"] == "win" for c in pu_done),
                "avg_pct": avg([c.get("result_pct") for c in pu_done]), "open": sum(c["status"] == "open" for c in pu)},
        "long": {"calls": len(lg), **{f"avg_vs_spy_{n}d": avg([c.get(f"vs_spy_{n}d") for c in lg]) for n in LONG_HORIZONS},
                 **{f"beat_spy_{n}d": _beat(lg, n) for n in LONG_HORIZONS}},
        "signal": {"calls": len(sg), **{f"avg_vs_spy_{n}d": avg([c.get(f"vs_spy_{n}d") for c in sg]) for n in SIGNAL_HORIZONS},
                   **{f"right_{n}d": _beat(sg, n) for n in SIGNAL_HORIZONS}},
    }


def _beat(calls, n):
    xs = [c[f"vs_spy_{n}d"] for c in calls if c.get(f"vs_spy_{n}d") is not None]
    return {"right": sum(x > 0 for x in xs), "of": len(xs)} if xs else None


def calls_from(day: str, setups: dict, verdicts: dict, brief: dict | None, us: set) -> list[dict]:
    """Today's calls from the dashboard data and the brief."""
    out = []
    for r in setups.get("swing", []):
        if r.get("entry") and r.get("stop") and r.get("target_2r"):
            out.append({"type": "swing", "ticker": r["ticker"], "date": day, "price": r.get("price"),
                        "entry": r["entry"], "stop": r["stop"], "target_2r": r["target_2r"]})
    for src, rows in (("scanner", setups.get("csp", [])), ("brief", setups.get("csp_ideas", []))):
        for r in rows:
            if r.get("strike") and r.get("expiration") and r.get("premium"):
                out.append({"type": "put", "ticker": r["ticker"], "date": day, "source": src, "price": r.get("price"),
                            "strike": r["strike"], "expiration": r["expiration"], "premium": r["premium"]})
    for t, v in verdicts.items():
        if v.get("verdict") == "Buy zone now" and t in us:
            out.append({"type": "long", "ticker": t, "date": day, "price": v.get("price")})
    for s in (brief or {}).get("signals", []):
        for side, key in (("bullish", "beneficiaries"), ("bearish", "hurt")):
            for t in s.get(key, []) or []:
                if t in us:
                    out.append({"type": "signal", "ticker": t, "date": day, "side": side, "title": s.get("title", "")[:120]})
    return out
