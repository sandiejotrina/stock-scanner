"""Builds every JSON file the dashboard reads, in site/data/.

The pipeline:
  themes (research/themes/*.json) -> every ticker in every supply chain
  + prices -> trend and setup status for each ticker
  + insider buys and Congress trades
  -> the Lineup: where theme, smart money and chart agree.

Each network step is allowed to fail on its own. The dashboard shows what failed.
"""

import json
import re
import shutil
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
RESEARCH = ROOT / "research"
OUT = ROOT / "site" / "data"


def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def _write(name: str, obj) -> None:
    path = OUT / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, default=str, separators=(",", ":")))


def yahoo_symbol(ticker: str) -> str:
    """BRK.B -> BRK-B for Yahoo. Foreign listings like 3110.T or 2330.TW pass through unchanged."""
    return ticker.replace(".", "-") if re.fullmatch(r"[A-Z]+\.[A-Z]", ticker) else ticker


def priceable(ticker: str) -> bool:
    """Anything Yahoo can price: US symbols plus foreign ones with an exchange suffix."""
    return re.fullmatch(r"[A-Z0-9]{1,6}(\.[A-Z]{1,3})?", ticker) is not None


def load_themes() -> list[dict]:
    themes = []
    for p in sorted((RESEARCH / "themes").glob("*.json")):
        t = _read(p, None)
        if t and t.get("layers"):
            themes.append(t)
    return themes


def theme_index(themes: list[dict]) -> dict[str, list[dict]]:
    """ticker -> every place it shows up across all supply chains."""
    idx: dict[str, list[dict]] = {}
    for th in themes:
        for layer in th["layers"]:
            for c in layer.get("companies", []):
                t = (c.get("ticker") or "").upper().strip()
                if not t:
                    continue
                idx.setdefault(t, []).append({
                    "theme": th["id"], "theme_name": th["name"], "layer": layer["name"],
                    "role": c.get("role", ""), "exposure": c.get("exposure", ""),
                    "chokepoint": bool(c.get("chokepoint")), "name": c.get("name", ""),
                    "us_tradable": c.get("us_tradable", True),
                    "exclude": bool(c.get("exclude_from_lineup")),
                })
    return idx


def tradable(ticker: str, places: list[dict]) -> bool:
    """US listed or ADR, i.e. something Yahoo and a US broker both know."""
    return any(p["us_tradable"] for p in places) and re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", ticker) is not None


# ---------- The Lineup ----------

EXPOSURE_PTS = {"pure play": 2, "major": 1, "partial": 0}


def lineup_score(ticker: str, places: list[dict], market: dict, insiders: dict, congress: dict, setups: set) -> dict:
    pts, reasons = 0.0, []

    themes = sorted({p["theme_name"] for p in places})
    if any(p["chokepoint"] for p in places):
        pts += 3
        reasons.append(("Chokepoint supplier", "accent"))
    best = max((EXPOSURE_PTS.get(p["exposure"], 0) for p in places), default=0)
    pts += best
    if best == 2:
        reasons.append(("Pure play", "accent"))
    if len(themes) > 1:
        pts += len(themes) - 1
        reasons.append((f"In {len(themes)} themes", "accent"))

    ins = insiders.get(ticker)
    if ins:
        pts += 3 if ins["cluster"] else 1.5
        reasons.append((f"{ins['insiders']} insider{'s' if ins['insiders'] > 1 else ''} bought", "up"))
        if any(k in ins["top_role"] for k in ("CEO", "CFO")):
            pts += 1

    con = congress.get(ticker)
    if con:
        if con["leaders"]:
            pts += 2
            reasons.append(("Congress leader bought", "up"))
        elif con["net_buyers"] > 0:
            pts += min(con["net_buyers"], 3) * 0.5
            reasons.append((f"{len(con['buyers'])} in Congress bought", "up"))
        elif con["net_buyers"] < 0:
            reasons.append(("Congress net selling", "down"))

    m = market.get(ticker)
    if m:
        if m["trend"] == "uptrend":
            pts += 2
            reasons.append(("Uptrend", "up"))
        elif m["trend"] == "downtrend":
            pts -= 2
            reasons.append(("Downtrend", "down"))
        if m.get("vs_spy_3m") is not None and m["vs_spy_3m"] > 0:
            pts += 1
        if m["breakout_setup"] or ticker in setups:
            pts += 2
            reasons.append(("Breakout setup now", "up"))

    return {
        "ticker": ticker, "name": places[0]["name"], "score": round(pts, 1), "themes": themes,
        "roles": [f"{p['theme_name']}: {p['layer']}" for p in places],
        "reasons": [{"text": t, "tone": tone} for t, tone in reasons],
        "chokepoint": any(p["chokepoint"] for p in places),
    }


# ---------- Build ----------

def build(offline: bool = False) -> dict:
    from .runner import load_settings, load_universe, run_csp, run_swing
    from .market import market_status

    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_settings()
    today = date.today()
    errors = []
    themes = load_themes()
    idx = theme_index(themes)
    market = _read(OUT / "market.json", {})
    insiders = _read(OUT / "insiders.json", {"by_ticker": []})
    congress = _read(OUT / "congress.json", {"by_ticker": [], "trades": [], "sources": [], "errors": []})
    setups = _read(OUT / "setups.json", {"swing": [], "csp": []})

    if not offline:
        from . import congress as congress_src
        from . import data as yahoo
        from . import insiders as insider_src

        us = sorted(set(load_universe()) | {t for t, places in idx.items() if tradable(t, places)})
        foreign = sorted(t for t in idx if priceable(t) and t not in us)
        sym = {t: yahoo_symbol(t) for t in us + foreign + ["SPY"]}
        try:
            raw = yahoo.load_prices(sorted(set(sym.values())))
            prices = {t: raw[s] for t, s in sym.items() if s in raw}
            spy = prices.pop("SPY")
            market = market_status(prices, spy, cfg["swing"])
            # Trade scans only on names a US broker can buy.
            us_prices = {t: df for t, df in prices.items() if t in us}
            swing = run_swing(us_prices, spy, cfg, yahoo, today)
            csp = run_csp(us_prices, cfg, yahoo, today)
            setups = {"swing": swing.to_dict("records"), "csp": csp.to_dict("records"), "as_of": today.isoformat()}
        except Exception as e:
            errors.append(f"Prices and scans: {e}")
        try:
            insiders = {"by_ticker": insider_src.fetch(days=30), "as_of": today.isoformat()}
        except Exception as e:
            errors.append(f"Insider buys: {e}")
        try:
            congress = {**congress_src.fetch(days=60), "as_of": today.isoformat()}
            errors.extend(congress.get("errors", []) if not congress["trades"] else [])
        except Exception as e:
            errors.append(f"Congress trades: {e}")

    ins_by = {r["ticker"]: r for r in insiders.get("by_ticker", [])}
    con_by = {r["ticker"]: r for r in congress.get("by_ticker", [])}
    swing_set = {r["ticker"] for r in setups.get("swing", [])}

    # Tag smart money and setups with their themes so the dashboard can connect the dots.
    for r in insiders.get("by_ticker", []):
        r["themes"] = sorted({p["theme_name"] for p in idx.get(r["ticker"], [])})
    for r in congress.get("by_ticker", []):
        r["themes"] = sorted({p["theme_name"] for p in idx.get(r["ticker"], [])})
    for bucket in ("swing", "csp"):
        for r in setups.get(bucket, []):
            r["themes"] = sorted({p["theme_name"] for p in idx.get(r["ticker"], [])})

    # Names flagged exclude_from_lineup (e.g. agreed buyouts, where upside is capped) stay on the
    # theme map but never rank.
    lineup = [lineup_score(t, places, market, ins_by, con_by, swing_set)
              for t, places in idx.items() if not any(p.get("exclude") for p in places)]
    lineup.sort(key=lambda r: r["score"], reverse=True)

    # Theme summaries: how the basket is trading.
    theme_cards = []
    for th in themes:
        tickers = sorted({c["ticker"].upper() for l in th["layers"] for c in l.get("companies", []) if c.get("ticker")})
        stats = [market[t] for t in tickers if t in market]
        chg = [s["chg_3m"] for s in stats if s.get("chg_3m") is not None]
        theme_cards.append({
            "id": th["id"], "name": th["name"], "thesis": th.get("thesis", ""),
            "money_source": th.get("money_source", ""), "updated": th.get("updated", ""),
            "companies": len(tickers), "chokepoints": sum(1 for l in th["layers"] for c in l.get("companies", []) if c.get("chokepoint")),
            "layers": len(th["layers"]),
            "pct_uptrend": round(100 * sum(s["trend"] == "uptrend" for s in stats) / len(stats)) if stats else None,
            "median_3m": round(float(pd.Series(chg).median()), 1) if chg else None,
            "emerging": bool(th.get("emerging")),
            "verified": th.get("verified", True),
        })
        _write(f"themes/{th['id']}.json", th)

    # Briefs: newest first.
    briefs = sorted((RESEARCH / "briefs").glob("*.json"), reverse=True)
    (OUT / "briefs").mkdir(exist_ok=True)
    for b in briefs:
        shutil.copy(b, OUT / "briefs" / b.name)

    _write("themes.json", theme_cards)
    _write("lineup.json", lineup)
    _write("market.json", market)
    _write("insiders.json", insiders)
    _write("congress.json", congress)
    _write("setups.json", setups)
    _write("tickers.json", idx)
    meta = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "briefs": [b.stem for b in briefs],
        "errors": errors,
        "prices_as_of": setups.get("as_of"),
        "congress_sources": congress.get("sources", []),
    }
    _write("meta.json", meta)
    return meta
