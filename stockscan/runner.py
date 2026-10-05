"""Runs the three buckets and writes the weekly report.

`source` is any object with the same functions as stockscan.data, so tests can
swap in fake data without touching the network.
"""

import json
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from . import data as yahoo
from .indicators import snapshot
from .scans import (
    cc_plan, csp_checks, csp_plan, days_until, earnings_ok, pick_option,
    support_level, swing_checks, swing_plan, swing_score,
)

ROOT = Path(__file__).resolve().parent.parent


def load_settings(path: Path = ROOT / "settings.json") -> dict:
    return json.loads(path.read_text())


def load_universe(path: Path = ROOT / "universe.txt") -> list[str]:
    tickers = []
    for line in path.read_text().splitlines():
        tickers.extend(line.split("#")[0].upper().split())
    return sorted(set(tickers))


def run_swing(prices: dict, spy: pd.DataFrame, cfg: dict, source, today: date) -> pd.DataFrame:
    rules, account = cfg["swing"], cfg["account"]
    rows = []
    for t, df in prices.items():
        s = snapshot(df, spy)
        checks = swing_checks(s, rules)
        if all(checks.values()):
            rows.append({"ticker": t, "score": swing_score(s), **s})
    if not rows:
        return pd.DataFrame()
    ranked = pd.DataFrame(rows).sort_values("score", ascending=False).head(rules["max_results"] * 2)

    out = []
    for _, r in ranked.iterrows():
        ev = source.company_events(r["ticker"])
        ok = earnings_ok(ev["earnings"], today, rules["min_days_to_earnings"])
        if ok is False:
            continue
        plan = swing_plan(r.to_dict(), account)
        out.append({
            "ticker": r["ticker"],
            "score": r["score"],
            "price": round(r["price"], 2),
            "vs_spy_3mo_pct": round(100 * (r["ret63"] - r["spy_ret63"]), 1),
            "base_depth_pct": round(100 * r["base_depth"], 1),
            "earnings": ev["earnings"] or "CHECK",
            **plan,
        })
        if len(out) >= rules["max_results"]:
            break
    return pd.DataFrame(out)


def run_csp(prices: dict, cfg: dict, source, today: date) -> pd.DataFrame:
    rules = cfg["csp"]
    out = []
    for t, df in prices.items():
        s = snapshot(df)
        if not all(csp_checks(s, rules).values()):
            continue
        ev = source.company_events(t)
        if ev["market_cap"] is not None and ev["market_cap"] < rules["min_market_cap"]:
            continue
        chain = source.option_chain(t, rules["min_dte"], rules["max_dte"], today)
        if chain is None:
            continue
        # No earnings before expiration. Unknown earnings date is flagged, not trusted.
        e_days = days_until(ev["earnings"], today)
        if e_days is not None and 0 <= e_days <= chain["dte"] + 2:
            continue
        support = support_level(s)
        opt = pick_option(chain["puts"], support, "put", rules)
        if opt is None:
            continue
        iv_hv = opt["iv"] / s["hv20"] if s["hv20"] else np.nan
        if iv_hv < rules["min_iv_to_hv"]:
            continue
        plan = csp_plan(opt, chain["dte"], s["price"])
        out.append({
            "ticker": t,
            "price": round(s["price"], 2),
            "support": round(support, 2),
            "expiration": chain["expiration"],
            "dte": chain["dte"],
            **plan,
            "iv_pct": round(100 * opt["iv"], 1),
            "iv_to_hv": round(iv_hv, 2),
            "open_interest": opt["open_interest"],
            "earnings": ev["earnings"] or "CHECK",
            "ex_dividend": ev["ex_dividend"],
        })
    df = pd.DataFrame(out)
    if df.empty:
        return df
    return df.sort_values("annualized_pct", ascending=False).head(rules["max_results"])


def run_covered_calls(prices: dict, cfg: dict, source, today: date) -> pd.DataFrame:
    rules = cfg["csp"]
    out = []
    for h in cfg.get("holdings", []):
        t, shares, basis = h["ticker"].upper(), h["shares"], h["cost_basis"]
        if shares < 100 or t not in prices:
            continue
        s = snapshot(prices[t])
        chain = source.option_chain(t, rules["min_dte"], rules["max_dte"], today)
        if chain is None:
            continue
        ev = source.company_events(t)
        # Strike at resistance: the 50 day high, and never below cost basis.
        target = max(s["high50"], basis, s["price"] * 1.03)
        opt = pick_option(chain["calls"], target, "call", rules)
        if opt is None:
            continue
        e_days = days_until(ev["earnings"], today)
        out.append({
            "ticker": t,
            "contracts": shares // 100,
            "price": round(s["price"], 2),
            "expiration": chain["expiration"],
            "dte": chain["dte"],
            **cc_plan(opt, chain["dte"], basis, s["price"]),
            "earnings_before_exp": None if e_days is None else 0 <= e_days <= chain["dte"],
            "ex_dividend": ev["ex_dividend"],
        })
    return pd.DataFrame(out)


def run_long_term(themes: dict, source) -> pd.DataFrame:
    out = []
    for theme, tickers in themes.items():
        for t in tickers:
            f = source.fundamentals(t)
            if f:
                out.append({"theme": theme, "ticker": t, **f})
    return pd.DataFrame(out)


def _fmt_long_term(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    df = df.copy()
    for col in ("revenue_growth", "earnings_growth", "gross_margin", "operating_margin"):
        df[col] = (100 * pd.to_numeric(df[col], errors="coerce")).round(1)
    df["market_cap"] = (pd.to_numeric(df["market_cap"], errors="coerce") / 1e9).round(1)
    df["fcf"] = (pd.to_numeric(df["fcf"], errors="coerce") / 1e9).round(2)
    for col in ("debt_to_equity", "forward_pe", "peg"):
        df[col] = pd.to_numeric(df[col], errors="coerce").round(2)
    return df.rename(columns={
        "market_cap": "mcap_$B", "fcf": "fcf_$B", "revenue_growth": "rev_growth_%",
        "earnings_growth": "eps_growth_%", "gross_margin": "gross_margin_%",
        "operating_margin": "op_margin_%",
    })


def _table(df: pd.DataFrame) -> str:
    if df.empty:
        return "_Nothing passed this week. That is a signal too: sit on cash._\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join("" if pd.isna(v) else str(v) for v in r.values) + " |")
    return "\n".join(lines) + "\n"


def write_report(today: date, swing, csp, cc, lt, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = today.isoformat()
    for name, df in (("swing", swing), ("csp", csp), ("covered_calls", cc), ("long_term", lt)):
        if not df.empty:
            df.to_csv(out_dir / f"{stamp}-{name}.csv", index=False)

    md = [
        f"# Weekly watchlist, {stamp}",
        "",
        "Free Yahoo data, end of day. Confirm every level on a TrendSpider chart before placing an order.",
        "`CHECK` means the earnings date was not available: look it up before trading.",
        "",
        "## 1. Swing breakouts",
        "Entry is a buy stop just above the 50 day high. Stop sits under the base, capped by your max stop %. "
        "Shares are sized so a stop out loses your set risk per trade.",
        "",
        _table(swing),
        "## 2. Cash secured puts",
        "Strike is the nearest liquid strike at or below support (20 day low, 50 or 200 day SMA). "
        "`iv_to_hv` is implied vol divided by 20 day realized vol. Above 1 means premium is rich. "
        "This stands in for IV rank, which needs paid data.",
        "",
        _table(csp),
        "## 3. Covered calls on your holdings",
        "Strike at or above the 50 day high and never below your cost basis.",
        "",
        _table(cc),
        "## 4. Long term themes: fundamentals",
        "Growth and margins in %, market cap and free cash flow in $B. Look for growth above 15%, "
        "rising margins, positive free cash flow, debt to equity under 100, and PEG under 2.",
        "",
        _table(_fmt_long_term(lt)),
    ]
    path = out_dir / f"{stamp}-watchlist.md"
    path.write_text("\n".join(md))
    return path


def run(today: date | None = None, source=yahoo, buckets=("swing", "csp", "cc", "long")) -> Path:
    today = today or date.today()
    cfg = load_settings()
    universe = load_universe()
    holdings = [h["ticker"].upper() for h in cfg.get("holdings", [])]
    prices = source.load_prices(sorted(set(universe + holdings + ["SPY"])))
    if "SPY" not in prices:
        raise RuntimeError("Could not download SPY. Check network access to Yahoo Finance.")
    spy = prices.pop("SPY")
    scan_prices = {t: df for t, df in prices.items() if t in universe}

    empty = pd.DataFrame()
    swing = run_swing(scan_prices, spy, cfg, source, today) if "swing" in buckets else empty
    csp = run_csp(scan_prices, cfg, source, today) if "csp" in buckets else empty
    cc = run_covered_calls(prices, cfg, source, today) if "cc" in buckets else empty
    themes = json.loads((ROOT / "themes.json").read_text())
    lt = run_long_term(themes, source) if "long" in buckets else empty
    return write_report(today, swing, csp, cc, lt, ROOT / "output")
