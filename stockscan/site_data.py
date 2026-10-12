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
    return re.fullmatch(r"[A-Z0-9][A-Z0-9\-]{0,8}(\.[A-Z]{1,3})?", ticker) is not None


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
                    "buyout": bool(c.get("buyout")),
                })
    return idx


ROLE_EXPOSURE = {"pure play": "pure play", "picks and shovels": "major", "adopter": "partial", "at risk": "partial"}


def load_innovations() -> list[dict]:
    out = []
    for p in sorted((RESEARCH / "innovations").glob("*.json")):
        ind = _read(p, None)
        if ind and ind.get("innovations"):
            out.append(ind)
    return out


def load_legends() -> list[dict]:
    return [lg for p in sorted((RESEARCH / "legends").glob("*.json")) if (lg := _read(p, None)) and lg.get("cik")]


def latest_legends(curated: list[dict], offline: bool, errors: list) -> list[dict]:
    """Curated files, replaced by a newer automatic 13F pull when there is one (fresh online, or from the last run)."""
    from . import legends as lg_src
    last = {lg["id"]: lg for lg in _read(OUT / "legends.json", []) if lg.get("auto")}
    cache = _read(OUT / "cusip_map.json", {})
    out, failed = [], []
    for lg in curated:
        best = last.get(lg["id"])
        if not offline:
            try:
                best = lg_src.refresh(lg, cache)
            except Exception as e:
                failed.append(f"{lg['name']} ({str(e)[:60]})")
        # Keep the curated text (style, view, sources); take holdings only from a quarter at least as new.
        if best and best.get("quarter", "") >= lg.get("quarter", ""):
            lg = {**lg, **{k: best[k] for k in ("quarter", "filed", "top", "bought", "sold", "auto") if k in best}}
        out.append(lg)
    if failed:  # one line, not eight: the tab still shows the hand checked copy
        errors.append(f"SEC 13F pull failed for {len(failed)} of {len(curated)} investors, showing the hand checked copy: {failed[0]}")
    if not offline:
        _write("cusip_map.json", cache)
    return out


def load_countries() -> list[dict]:
    out = []
    for p in sorted((RESEARCH / "countries").glob("*.json")):
        c = _read(p, None)
        if c and c.get("exposed") is not None:
            out.append(c)
    return out


def country_tickers(countries: list[dict]) -> set[str]:
    """US tradable names on the World tab (exposed stocks and country ETFs), so they get prices too."""
    return ({(e.get("ticker") or "").upper() for c in countries for e in c.get("exposed", []) if e.get("ticker")}
            | {c["proxy"].upper() for c in countries if c.get("proxy")}) - {""}


def add_innovations(idx: dict[str, list[dict]], industries: list[dict]) -> None:
    """Innovation stocks join the same ticker index as the themes, so they get prices, smart money and verdicts.
    'At risk' names are tracked but never rank in the Lineup."""
    for ind in industries:
        for inn in ind["innovations"]:
            for c in inn.get("stocks", []):
                t = (c.get("ticker") or "").upper().strip()
                if not t or t == "EW":
                    continue
                role = c.get("role", "")
                idx.setdefault(t, []).append({
                    "theme": f"innovation/{ind['id']}", "theme_name": f"{ind['industry']}: {inn['name']}",
                    "layer": role.capitalize(), "role": c.get("why", ""), "exposure": ROLE_EXPOSURE.get(role, "partial"),
                    "chokepoint": False, "name": c.get("name", ""), "us_tradable": c.get("us_tradable", True),
                    "exclude": role == "at risk" or bool(c.get("buyout") or c.get("exclude_from_lineup")),
                    "buyout": bool(c.get("buyout")), "kind": "innovation", "innovation": inn["id"], "innovation_role": role,
                })


def tradable(ticker: str, places: list[dict]) -> bool:
    """US listed or ADR, i.e. something Yahoo and a US broker both know."""
    return any(p["us_tradable"] for p in places) and re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", ticker) is not None


# ---------- The Lineup ----------

EXPOSURE_PTS = {"pure play": 2, "major": 1, "partial": 0}


def smart_money(ticker: str, insiders: dict, congress: dict, legends: dict) -> list[dict]:
    """Who with real information or a great record is buying (or selling) this name: [{"text", "tone"}]."""
    out = []
    ins = insiders.get(ticker)
    if ins:
        who = "CEO or CFO" if any(k in ins.get("top_role", "") for k in ("CEO", "CFO")) else f"{ins['insiders']} insider{'s' if ins['insiders'] > 1 else ''}"
        out.append({"text": f"Insiders buying ({who}{', cluster' if ins.get('cluster') else ''}, last {ins.get('last_trade', '')})", "tone": "up"})
    con = congress.get(ticker)
    if con and con.get("leaders"):
        out.append({"text": f"Congress leader bought: {', '.join(con['leaders'])}", "tone": "up"})
    elif con and con.get("net_buyers", 0) > 0:
        out.append({"text": f"{len(con['buyers'])} in Congress bought", "tone": "up"})
    elif con and con.get("net_buyers", 0) < 0:
        out.append({"text": "Congress net selling", "tone": "down"})
    lg = legends.get(ticker)
    if lg and lg["buyers"]:
        out.append({"text": f"Great minds bought: {', '.join(lg['buyers'])}", "tone": "up"})
    if lg and lg["sellers"]:
        out.append({"text": f"Great minds sold: {', '.join(lg['sellers'])}", "tone": "down"})
    return out


LONGTERM_QUOTES = 10  # puts priced per refresh for "right price, chart not ready" names


def build_longterm(lineup, verdicts, idx, market, prices, cfg, today, offline, errors) -> dict:
    """The Long term tab: buy now (price and chart ready), get paid to wait (right price, chart not ready:
    sell a put at support instead), and the watch list (good business, price too high). US tradable only."""
    rank = {r["ticker"]: i + 1 for i, r in enumerate(lineup)}
    lu = {r["ticker"]: r for r in lineup}

    def row(t, v):
        places = idx.get(t, [])
        return {"ticker": t, "name": places[0]["name"] if places else t, "price": v.get("price"),
                "zone": v.get("zone"), "fair": (v.get("fair") or {}).get("mid"), "rank": rank.get(t),
                "score": (lu.get(t) or {}).get("score"), "themes": sorted({p["theme_name"] for p in places})[:3],
                "reason": (v.get("reasons") or [""])[0], "failed": (v.get("chart") or {}).get("failed", []),
                "put_strike": v.get("put_strike_idea"), "chg_1m": (market.get(t) or {}).get("chg_1m")}
    us = [t for t, v in verdicts.items() if tradable(t, idx.get(t, [])) and t in market]
    by = lambda kind: sorted((row(t, verdicts[t]) for t in us if verdicts[t]["verdict"] == kind),
                             key=lambda r: (r["rank"] or 9999))
    buy, wait, watch = by("Buy zone now"), by("Buy zone, wait for the chart"), by("Accumulate on pullback")

    last = {r["ticker"]: r for r in _read(OUT / "longterm.json", {}).get("wait", []) if r.get("quote")}
    if not offline and prices:
        from . import data as yahoo
        from .runner import quote_put_ideas
        ideas = [{"ticker": r["ticker"], "strike": r["put_strike"], "why": "", "added": today.isoformat()}
                 for r in wait[:LONGTERM_QUOTES] if r["put_strike"]]
        try:
            for q in quote_put_ideas(ideas, prices, cfg, yahoo, today):
                last[q["ticker"]] = {"quote": {k: q.get(k) for k in ("expiration", "strike", "premium", "annualized_pct",
                                                                    "breakeven", "earnings", "status")}, "quoted": today.isoformat()}
        except Exception as e:
            errors.append(f"Long term put quotes: {e}")
    for r in wait:
        if r["ticker"] in last:
            r["quote"], r["quoted"] = last[r["ticker"]]["quote"], last[r["ticker"]].get("quoted")
    return {"buy": buy, "wait": wait, "watch": watch[:40], "as_of": today.isoformat()}


def lineup_score(ticker: str, places: list[dict], market: dict, insiders: dict, congress: dict, setups: set,
                 legends: dict | None = None) -> dict:
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
        pts += min(len(themes) - 1, 2)  # capped: showing up everywhere should not beat being a chokepoint
        reasons.append((f"In {len(themes)} themes", "accent"))

    ins = insiders.get(ticker)
    if ins:
        pts += 3 if ins["cluster"] else 1.5
        reasons.append((f"{ins['insiders']} insider{'s' if ins['insiders'] > 1 else ''} bought", "up"))
        if any(k in ins["top_role"] for k in ("CEO", "CFO")):
            pts += 1

    lg = (legends or {}).get(ticker)
    if lg and lg["buyers"]:
        pts += min(len(lg["buyers"]), 2)
        reasons.append((f"Great minds buying: {', '.join(lg['buyers'])}", "up"))
    if lg and lg["sellers"]:
        pts -= min(len(lg["sellers"]) * 0.5, 1)
        reasons.append((f"Great minds selling: {', '.join(lg['sellers'])}", "down"))

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
        ud = m.get("up_down_vol")
        if ud is not None and ud >= 1.2:
            pts += 1
            reasons.append(("Buyers' volume", "up"))
        elif ud is not None and ud < 0.8:
            pts -= 1
            reasons.append(("Sellers' volume", "down"))
        if m["breakout_setup"] or ticker in setups:
            pts += 2
            reasons.append(("Breakout setup now", "up"))

    return {
        "ticker": ticker, "name": places[0]["name"], "score": round(pts, 1), "themes": themes,
        "roles": [f"{p['theme_name']}: {p['layer']}" for p in places],
        "reasons": [{"text": t, "tone": tone} for t, tone in reasons],
        "chokepoint": any(p["chokepoint"] for p in places),
    }


# ---------- Fundamentals ----------

def refresh_fundamentals(cache: dict, tickers: list[str], source, today, max_age_days: int = 6, limit: int = 400) -> dict:
    """Fundamentals change slowly, so refresh only stale entries, oldest first, a few hundred per run."""
    from concurrent.futures import ThreadPoolExecutor

    def stale(t):
        as_of = (cache.get(t) or {}).get("as_of")
        return not as_of or (today - date.fromisoformat(as_of)).days >= max_age_days

    todo = sorted((t for t in tickers if stale(t)), key=lambda t: (cache.get(t) or {}).get("as_of", ""))[:limit]
    with ThreadPoolExecutor(max_workers=6) as pool:
        for t, f in zip(todo, pool.map(lambda t: source.valuation_inputs(yahoo_symbol(t)), todo)):
            if f:
                cache[t] = {**f, "as_of": today.isoformat()}
    return cache


# ---------- Build ----------

def vix_status(df, today: date) -> dict:
    """The fear gauge in plain words, and what it means for selling puts and for swing entries."""
    close = df["Close"].dropna()
    level = float(close.iloc[-1])
    year = close.tail(252)
    week_ago = float(close.iloc[-6]) if len(close) > 5 else level
    if level < 15:
        zone, puts, swing = ("Calm", "Premiums are thin. Sell fewer puts or go a little closer to the money only on names you want to own.",
                             "Breakouts tend to follow through. Normal size.")
    elif level < 20:
        zone, puts, swing = ("Normal", "Premiums are average. Stick to the usual rules.", "Normal conditions. Normal size.")
    elif level < 30:
        zone, puts, swing = ("Elevated", "Premiums are rich, which pays you to wait. Sell further below support and size smaller.",
                             "Breakouts fail more often. Use smaller size and honor stops.")
    else:
        zone, puts, swing = ("Fear", "Premiums are very rich, but so is the risk. Only sell puts on names you would gladly own, well below support.",
                             "Most breakouts fail in panics. Mostly wait.")
    return {
        "level": round(level, 2),
        "chg_1w": round(100 * (level / week_ago - 1), 1) if week_ago else None,
        "pct_1y": round(100 * float((year < level).mean())),
        "low_1y": round(float(year.min()), 2), "high_1y": round(float(year.max()), 2),
        "zone": zone, "puts": puts, "swing": swing,
        "history": [round(float(x), 2) for x in close.tail(60)],
        "as_of": str(close.index[-1].date()) if hasattr(close.index[-1], "date") else today.isoformat(),
    }


def load_put_ideas(today: date, max_age_days: int = 14) -> list[dict]:
    """Puts the daily brief suggested (research/put_ideas.json). Old ideas drop off after two weeks."""
    ideas = _read(RESEARCH / "put_ideas.json", [])
    fresh = []
    for i in ideas if isinstance(ideas, list) else []:
        if not i.get("ticker"):
            continue
        try:
            age = (today - date.fromisoformat(i.get("added", ""))).days
        except ValueError:
            age = 0
        if age <= max_age_days:
            fresh.append(i)
    return fresh


LINEUP_TOP = 30


def theme_note(th: dict) -> dict | None:
    """The newest entry of a theme's "changes" log: {"date", "what"}."""
    log = [c for c in th.get("changes", []) if c.get("date") and c.get("what")]
    return max(log, key=lambda c: c["date"]) if log else None


def mark_new(lineup, setups, insiders, congress, verdicts, themes, theme_cards, industries=(), industry_cards=(), now=None, brief_day: str = "",
             countries=(), country_cards=()) -> dict:
    """Flags rows that are new since about the last brief ("new": true, verdicts also get "was") and
    returns the summary for the What's new box. History lives in seen.json."""
    from .changes import track
    cur = {f"lineup:{r['ticker']}": "1" for r in lineup[:LINEUP_TOP]}
    for bucket in ("swing", "csp", "csp_ideas"):
        cur.update({f"{bucket}:{r['ticker']}": "1" for r in setups.get(bucket, [])})
    cur.update({f"insider:{r['ticker']}": "1" for r in insiders.get("by_ticker", [])})
    cur.update({f"congress:{r['ticker']}": "1" for r in congress.get("by_ticker", []) if r.get("net_buyers", 0) > 0 or r.get("leaders")})
    cur.update({f"verdict:{t}": v["verdict"] for t, v in verdicts.items()})
    notes = {th["id"]: theme_note(th) for th in themes}
    cur.update({f"theme:{i}": f"{n['date']} {n['what']}" if n else "1" for i, n in notes.items()})
    ind_notes = {ind["id"]: theme_note(ind) for ind in industries}
    cty_notes = {c["id"]: theme_note(c) for c in countries}
    cur.update({f"country:{i}": f"{n['date']} {n['what']}" if n else "1" for i, n in cty_notes.items()})
    cur.update({f"industry:{i}": f"{n['date']} {n['what']}" if n else "1" for i, n in ind_notes.items()})
    seen, new = track(_read(OUT / "seen.json", {}), cur, now)
    _write("seen.json", seen)

    def flag(rows, prefix):
        for r in rows:
            r["new"] = f"{prefix}:{r['ticker']}" in new
    for i, r in enumerate(lineup):
        r["new"] = i < LINEUP_TOP and f"lineup:{r['ticker']}" in new
        r["verdict_was"] = None
    for bucket in ("swing", "csp", "csp_ideas"):
        flag(setups.get(bucket, []), bucket)
    flag(insiders.get("by_ticker", []), "insider")
    flag(congress.get("by_ticker", []), "congress")
    moved = []
    for t, v in verdicts.items():
        n = new.get(f"verdict:{t}")
        v["new"] = bool(n and n["was"])  # a name joining the map is not a verdict change
        v["was"] = n["was"] if v["new"] else None
        if v["new"]:
            for r in lineup:
                if r["ticker"] == t:
                    r["verdict_was"] = n["was"]
        if v["new"] and v["verdict"] == "Buy zone now":
            moved.append({"ticker": t, "was": n["was"]})
    theme_new = []
    for card in theme_cards:
        n = notes.get(card["id"])
        card["new"] = f"theme:{card['id']}" in new and (n is None or n["date"] >= brief_day)
        card["latest_change"] = n
        if card["new"]:
            theme_new.append({"id": card["id"], "name": card["name"], **(n or {"what": "New theme"})})

    ind_new = []
    for card in industry_cards:
        n = ind_notes.get(card["id"])
        # Only a change logged since the latest brief counts; old history entries never show as new.
        card["new"] = bool(n) and n["date"] >= brief_day and f"industry:{card['id']}" in new
        card["latest_change"] = n
        if card["new"]:
            ind_new.append({"id": card["id"], "name": card["industry"], **n})

    cty_new = []
    for card in country_cards:
        n = cty_notes.get(card["id"])
        card["new"] = bool(n) and n["date"] >= brief_day and f"country:{card['id']}" in new
        card["latest_change"] = n
        if card["new"]:
            cty_new.append({"id": card["id"], "name": card["country"], **n})

    def keys(prefix, pool=None):
        return sorted(k.split(":", 1)[1] for k in (pool if pool is not None else new) if k.startswith(prefix + ":"))
    return {
        "lineup": [r["ticker"] for r in lineup[:LINEUP_TOP] if r["new"]],
        "buy_zone": moved,
        "swing": keys("swing"), "swing_dropped": keys("swing", new["_gone"]),
        "csp": keys("csp"), "csp_ideas": keys("csp_ideas"),
        "insiders": keys("insider"), "congress": keys("congress"),
        "themes": theme_new, "innovations": ind_new, "countries": cty_new,
        "as_of": seen["updated"],
    }


def build(offline: bool = False, quote_ideas: bool = False) -> dict:
    """offline skips the network. quote_ideas (with offline) still prices the brief's put ideas,
    which takes a few seconds, so a brief push shows real premiums the same morning."""
    from .runner import load_settings, load_universe, quote_put_ideas, run_csp, run_swing
    from .market import market_status

    OUT.mkdir(parents=True, exist_ok=True)
    cfg = load_settings()
    today = date.today()
    errors = []
    themes = load_themes()
    industries = load_innovations()
    countries = load_countries()
    idx = theme_index(themes)
    add_innovations(idx, industries)
    market = _read(OUT / "market.json", {})
    insiders = _read(OUT / "insiders.json", {"by_ticker": []})
    congress = _read(OUT / "congress.json", {"by_ticker": [], "trades": [], "sources": [], "errors": []})
    setups = _read(OUT / "setups.json", {"swing": [], "csp": []})
    vix = _read(OUT / "vix.json", {})
    ideas = load_put_ideas(today)
    idea_rows = None  # None means keep the last quotes
    prices: dict = {}
    fundamentals = _read(OUT / "fundamentals.json", {})

    if not offline:
        from . import congress as congress_src
        from . import data as yahoo
        from . import insiders as insider_src

        us = sorted(set(load_universe()) | {t for t, places in idx.items() if tradable(t, places)}
                    | {i["ticker"].upper() for i in ideas} | {t for t in country_tickers(countries) if priceable(t)})
        foreign = sorted(t for t in idx if priceable(t) and t not in us)
        sym = {t: yahoo_symbol(t) for t in us + foreign + ["SPY"]}
        sym["^VIX"] = "^VIX"
        try:
            raw = yahoo.load_prices(sorted(set(sym.values())))
            prices = {t: raw[s] for t, s in sym.items() if s in raw}
            spy = prices.pop("SPY")
            if (v := prices.pop("^VIX", None)) is not None:
                vix = vix_status(v, today)
            market = market_status(prices, spy, cfg["swing"])
            # Trade scans only on names a US broker can buy.
            us_prices = {t: df for t, df in prices.items() if t in us}
            swing = run_swing(us_prices, spy, cfg, yahoo, today)
            csp = run_csp(us_prices, cfg, yahoo, today)
            setups = {"swing": swing.to_dict("records"), "csp": csp.to_dict("records"), "as_of": today.isoformat(),
                      "csp_ideas": setups.get("csp_ideas", [])}
        except Exception as e:
            errors.append(f"Prices and scans: {e}")
        try:  # separate, so a bad option quote can never stop the main scans again
            idea_rows = quote_put_ideas(ideas, prices, cfg, yahoo, today)
        except Exception as e:
            errors.append(f"Put ideas: {e}")
        try:
            fundamentals = refresh_fundamentals(fundamentals, [t for t in idx if t in market], yahoo, today)
        except Exception as e:
            errors.append(f"Fundamentals: {e}")
        try:
            insiders = {"by_ticker": insider_src.fetch(days=30), "as_of": today.isoformat()}
        except Exception as e:
            errors.append(f"Insider buys: {e}")
        try:
            congress = {**congress_src.fetch(days=60), "as_of": today.isoformat()}
            # Quiver needs a paid key now, so only report failures of the official sources.
            errors.extend(e for e in congress.get("errors", []) if not e.startswith("Quiver"))
        except Exception as e:
            errors.append(f"Congress trades: {e}")

    if offline and quote_ideas:  # also refreshes the VIX, so the morning brief has it
        from . import data as yahoo
        try:
            want = sorted({i["ticker"].upper() for i in ideas})
            raw = yahoo.load_prices([yahoo_symbol(t) for t in want] + ["^VIX"])
            if raw.get("^VIX") is not None:
                vix = vix_status(raw["^VIX"], today)
            idea_rows = quote_put_ideas(ideas, {t: raw.get(yahoo_symbol(t)) for t in want}, cfg, yahoo, today)
        except Exception as e:
            errors.append(f"Put ideas: {e}")
    if idea_rows is None:
        # Keep the last quotes for ideas still listed, and show new ones as waiting for a quote.
        last = {r["ticker"]: r for r in setups.get("csp_ideas", [])}
        idea_rows = [last.get(i["ticker"].upper()) or {"ticker": i["ticker"].upper(), "idea_strike": i.get("strike"),
                                                        "why": i.get("why", ""), "added": i.get("added", ""),
                                                        "status": "Waiting for the next price refresh"}
                     for i in ideas]
    if idea_rows:
        stamp = today.isoformat() if not offline or quote_ideas else None
        for r in idea_rows:
            r.setdefault("quoted", stamp)
    setups["csp_ideas"] = idea_rows

    # Excluded names (agreed buyouts and the like) never show up as trade ideas either.
    excluded = {t for t, places in idx.items() if any(p.get("exclude") for p in places)}
    for bucket in ("swing", "csp", "csp_ideas"):
        setups[bucket] = [r for r in setups.get(bucket, []) if r.get("ticker") not in excluded]

    ins_by = {r["ticker"]: r for r in insiders.get("by_ticker", [])}
    con_by = {r["ticker"]: r for r in congress.get("by_ticker", [])}
    swing_set = {r["ticker"] for r in setups.get("swing", [])}

    # Tag smart money and setups with their themes so the dashboard can connect the dots.
    for r in insiders.get("by_ticker", []):
        r["themes"] = sorted({p["theme_name"] for p in idx.get(r["ticker"], [])})
    for r in congress.get("by_ticker", []):
        r["themes"] = sorted({p["theme_name"] for p in idx.get(r["ticker"], [])})
    for bucket in ("swing", "csp", "csp_ideas"):
        for r in setups.get(bucket, []):
            r["themes"] = sorted({p["theme_name"] for p in idx.get(r["ticker"], [])})

    # Names flagged exclude_from_lineup (e.g. agreed buyouts, where upside is capped) stay on the
    # theme map but never rank.
    from .legends import signals as legend_signals
    legends = latest_legends(load_legends(), offline, errors)
    legend_by = legend_signals(legends)
    for bucket in ("swing", "csp", "csp_ideas"):
        for r in setups.get(bucket, []):
            r["smart"] = smart_money(r["ticker"], ins_by, con_by, legend_by)
    lineup = [lineup_score(t, places, market, ins_by, con_by, swing_set, legend_by)
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

    # Verdicts for every tracked stock that has prices.
    from .valuation import verdict
    verdicts = {}
    for t, places in idx.items():
        if t not in market:
            continue
        premium = any(p["chokepoint"] or p["exposure"] == "pure play" for p in places)
        verdicts[t] = verdict(t, fundamentals.get(t, {}), market[t], premium)
        if any(p.get("buyout") for p in places):
            verdicts[t].update(verdict="Buyout pending", tone="down",
                               reasons=["An agreed takeover caps the upside near the deal price. Not a long term buy."])
    for r in lineup:
        v = verdicts.get(r["ticker"])
        r["verdict"] = v["verdict"] if v else "Not enough data"
        r["verdict_tone"] = v["tone"] if v else ""

    longterm = build_longterm(lineup, verdicts, idx, market, prices, cfg, today, offline, errors)

    # Innovation radar: one file per industry plus an index.
    industry_cards = []
    for ind in industries:
        stages = [inn.get("stage", "") for inn in ind["innovations"]]
        tickers = {(c.get("ticker") or "").upper() for inn in ind["innovations"] for c in inn.get("stocks", []) if c.get("ticker")}
        buys = sorted(t for t in tickers if verdicts.get(t, {}).get("verdict") == "Buy zone now")
        industry_cards.append({
            "id": ind["id"], "industry": ind["industry"], "summary": ind.get("summary", ""), "updated": ind.get("updated", ""),
            "innovations": [{"id": i["id"], "name": i["name"], "stage": i.get("stage", "")} for i in ind["innovations"]],
            "stocks": len(tickers), "buy_zone_now": buys,
            "stage_counts": {st: stages.count(st) for st in ("lab", "pilot", "early adoption", "mass market")},
        })
        _write(f"innovations/{ind['id']}.json", ind)

    # World: one file per country plus an index.
    country_cards = []
    for c in countries:
        names = [e["ticker"].upper() for e in c.get("exposed", []) if e.get("ticker")]
        proxy = (c.get("proxy") or "").upper()
        country_cards.append({
            "id": c["id"], "country": c["country"], "summary": c.get("summary", ""), "updated": c.get("updated", ""),
            "for_you": c.get("for_you", ""),
            "proxy": proxy, "proxy_3m": (market.get(proxy) or {}).get("chg_3m"), "proxy_1m": (market.get(proxy) or {}).get("chg_1m"),
            "proxy_trend": (market.get(proxy) or {}).get("trend"),
            "tickers": names, "hurt": [e["ticker"] for e in c.get("exposed", []) if e.get("direction") == "hurt"],
            "helped": [e["ticker"] for e in c.get("exposed", []) if e.get("direction") == "helped"],
            "exposed": [{"ticker": e["ticker"].upper(), "direction": e.get("direction", ""), "exposure": e.get("exposure", "")}
                        for e in c.get("exposed", []) if e.get("ticker")],
        })
        _write(f"countries/{c['id']}.json", c)

    # Briefs: newest first.
    briefs = sorted((RESEARCH / "briefs").glob("*.json"), reverse=True)
    (OUT / "briefs").mkdir(exist_ok=True)
    for b in briefs:
        shutil.copy(b, OUT / "briefs" / b.name)

    briefs = sorted((RESEARCH / "briefs").glob("*.json"), reverse=True)
    changes = mark_new(lineup, setups, insiders, congress, verdicts, themes, theme_cards, industries, industry_cards,
                       countries=countries, country_cards=country_cards,
                       brief_day=briefs[0].stem if briefs else "")

    _write("themes.json", theme_cards)
    _write("changes.json", changes)
    _write("lineup.json", lineup)
    _write("market.json", market)
    _write("insiders.json", insiders)
    _write("congress.json", congress)
    _write("setups.json", setups)
    _write("vix.json", vix)
    _write("tickers.json", idx)
    _write("verdicts.json", verdicts)
    _write("fundamentals.json", fundamentals)
    _write("innovations.json", industry_cards)
    _write("countries.json", country_cards)
    _write("legends.json", legends)
    _write("longterm.json", longterm)
    _write("legend_signals.json", legend_by)
    model = _read(RESEARCH / "models" / "all-weather.json", None)
    if model:
        # Dashboard names that fit the stock sleeve now: Lineup top 30 in the buy zone.
        model["buy_zone_names"] = [r["ticker"] for r in lineup[:LINEUP_TOP] if r.get("verdict") == "Buy zone now"]
        _write("model.json", model)
    meta = {
        "generated": datetime.now(timezone.utc).isoformat(timespec="minutes"),
        "briefs": [b.stem for b in briefs],
        "errors": errors,
        "prices_as_of": setups.get("as_of"),
        "congress_sources": congress.get("sources", []),
    }
    _write("meta.json", meta)
    return meta
