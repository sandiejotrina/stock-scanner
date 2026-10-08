"""Daily snapshot of the dashboard as one HTML document, for archiving (Google Drive converts it to a Doc).

    python -m stockscan.report            writes output/snapshot-<date>.html and prints the path
"""

import html
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "site" / "data"
SITE_URL = "https://sandiejotrina.github.io/stock-scanner/"


def _read(name, default):
    try:
        return json.loads((DATA / name).read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def e(x) -> str:
    return html.escape("" if x is None else str(x))


HL = "#FFF59D"  # Google Docs keeps this as a yellow highlight
NEW = f'<span style="background-color:{HL}"><b>NEW</b></span> '


def _previous(path: str, day: str, root: Path = ROOT):
    """The file as it was in the last daily brief before `day` (what the previous snapshot showed), or None."""
    try:
        sha = subprocess.run(["git", "log", "-1", "--format=%H", "--grep=^Daily brief ", f"--before={day} 00:00 -0700"],
                             cwd=root, capture_output=True, text=True, timeout=20).stdout.strip()
        if not sha:
            return None
        out = subprocess.run(["git", "show", f"{sha}:site/data/{path}"], cwd=root, capture_output=True, text=True, timeout=20)
        return json.loads(out.stdout) if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None


def table(cols: list[tuple[str, str]], rows: list[dict]) -> str:
    """Rows with a truthy "_new" get a yellow background and a NEW tag (plus "_note") on the ticker."""
    if not rows:
        return "<p><i>Nothing on the last run.</i></p>"
    head = "".join(f"<th>{e(label)}</th>" for _, label in cols)
    body = ""
    for r in rows:
        cells = [e(r.get(k)) for k, _ in cols]
        style = ""
        if r.get("_new"):
            style = f' style="background-color:{HL}"'
            at = next((i for i, (k, _) in enumerate(cols) if k == "ticker"), 0)
            cells[at] = NEW + cells[at] + (f" <i>({e(r['_note'])})</i>" if r.get("_note") else "")
        body += f"<tr{style}>" + "".join(f"<td{style}>{c}</td>" for c in cells) + "</tr>"
    return f'<table border="1" cellpadding="4" cellspacing="0"><tr>{head}</tr>{body}</table>'


def build(day: str | None = None, previous=_previous) -> str:
    """previous(path, day) returns that data file as of the last snapshot, for the NEW highlights."""
    meta = _read("meta.json", {})
    briefs = meta.get("briefs", [])
    day = day or (briefs[0] if briefs else date.today().isoformat())
    old = {name: previous(name, day) for name in
           ("lineup.json", "insiders.json", "congress.json", "verdicts.json", "setups.json")}
    have_old = any(v is not None for v in old.values())

    def seen(name, rows, key="ticker"):
        return {r.get(key) for r in rows} if old[name] is not None else None

    def mark(rows, before):
        # Before is None when there is no earlier snapshot: then nothing is marked new.
        return [{**r, "_new": before is not None and r.get("ticker") not in before} for r in rows]
    b = _read(f"briefs/{day}.json", None) or {}
    lineup = _read("lineup.json", [])[:15]
    market = _read("market.json", {})
    insiders = _read("insiders.json", {}).get("by_ticker", [])
    congress = _read("congress.json", {})
    setups = _read("setups.json", {})

    out = [f"<h1>Money Trail daily snapshot, {e(day)}</h1>",
           f'<p>Dashboard: <a href="{SITE_URL}">{SITE_URL}</a>. Data refreshed {e(meta.get("generated"))} UTC.</p>',
           "<p><b>Research, not advice.</b> AI assisted research. Free data can be late or wrong.</p>"]
    whats_new_at = len(out)  # filled in at the end, once every section knows what changed
    news = []

    if b:
        out += [f"<h2>Brief: {e(b.get('headline'))}</h2>",
                f"<p><b>Market:</b> {e(b.get('regime', {}).get('stance'))}. {e(b.get('summary'))}</p>"]
        levels = b.get("regime", {}).get("levels", [])
        out.append(table([("name", "Level"), ("value", "Value"), ("change_1w", "1 week")], levels))
        inbox = b.get("inbox")
        if inbox:
            out.append(f"<h3>Your alerts, filtered ({e(inbox.get('kept', len(inbox.get('items', []))))} of "
                       f"{e(inbox.get('scanned', '?'))} market emails mattered)</h3>")
            items = [{**i, "priority": "Act" if i.get("priority") == "act" else "Watch",
                      "tickers": ", ".join(i.get("tickers", []))} for i in inbox.get("items", [])]
            out.append(table([("priority", "Priority"), ("tickers", "Tickers"), ("source", "Source"),
                              ("what", "What"), ("action", "Do")], items))
        acts = b.get("actions", {})
        out += ["<h3>What it means</h3>",
                f"<p><b>Swing:</b> {e(acts.get('swing'))}</p>",
                f"<p><b>Puts and covered calls:</b> {e(acts.get('options'))}</p>",
                f"<p><b>Long term:</b> {e(acts.get('long_term'))}</p>",
                "<h3>Signals</h3>"]
        for s in b.get("signals", []):
            out += [f"<h4>{e(s.get('title'))} ({e(s.get('category'))}, confidence {e(s.get('confidence'))})</h4>",
                    f"<p>{e(s.get('what_happened'))}</p>",
                    f"<p><b>So what:</b> {e(s.get('so_what'))}</p>",
                    f"<p><b>Benefits:</b> {e(', '.join(s.get('beneficiaries', [])))}. "
                    f"<b>Hurt:</b> {e(', '.join(s.get('hurt', [])))}.</p>"]
        out += ["<h3>Calendar</h3>", table([("date", "Date"), ("event", "Event"), ("why_it_matters", "Why")], b.get("calendar", []))]

    rows = [{**r, "reasons": ", ".join(x["text"] for x in r["reasons"]), "themes": ", ".join(r["themes"]),
             "chg_3m": (market.get(r["ticker"]) or {}).get("chg_3m")} for r in lineup]
    rows = mark(rows, seen("lineup.json", (old["lineup.json"] or [])[:15]))
    if new := [r["ticker"] for r in rows if r["_new"]]:
        news.append(f"New on the Lineup top 15: {', '.join(new)}")
    out += ["<h2>Lineup: top 15</h2>",
            table([("score", "Score"), ("ticker", "Ticker"), ("name", "Company"), ("reasons", "Why"),
                   ("chg_3m", "3 mo %"), ("themes", "Themes")], rows)]

    clusters = [r for r in insiders if r.get("cluster") or r.get("themes")][:15]
    clusters = mark(clusters, seen("insiders.json", (old["insiders.json"] or {}).get("by_ticker", [])))
    if new := [r["ticker"] for r in clusters if r["_new"]]:
        news.append(f"New insider buying: {', '.join(new)}")
    out += ["<h2>Insider buying: clusters and theme names</h2>",
            table([("ticker", "Ticker"), ("company", "Company"), ("insiders", "Insiders"), ("top_role", "Most senior"),
                   ("total_value", "Total $"), ("last_trade", "Last trade")], clusters)]

    con = [{**r, "buyers": ", ".join(r["buyers"]), "leaders": ", ".join(r["leaders"])}
           for r in congress.get("by_ticker", []) if r.get("leaders") or r.get("net_buyers", 0) > 0][:15]
    con = mark(con, seen("congress.json", (old["congress.json"] or {}).get("by_ticker", [])))
    if new := [r["ticker"] for r in con if r["_new"]]:
        news.append(f"New Congress buying: {', '.join(new)}")
    out += [f"<h2>Congress: net buying (source: {e(', '.join(congress.get('sources', [])) or 'none')})</h2>",
            table([("ticker", "Ticker"), ("buyers", "Bought"), ("leaders", "Leader"), ("buy_amount_min", "At least $"),
                   ("last_filed", "Filed")], con)]

    verdicts = _read("verdicts.json", {})
    old_v = old["verdicts.json"]
    names = {t: places[0].get("name", "") for t, places in _read("tickers.json", {}).items() if places}
    def vrows(kind):
        rows = []
        for t, v in sorted(verdicts.items()):
            if v.get("verdict") == kind and v.get("zone"):
                was = (old_v.get(t) or {}).get("verdict") if old_v is not None else kind
                rows.append({"ticker": t, "name": names.get(t, ""), "price": v.get("price"),
                             "zone": f"{v['zone']['low']} to {v['zone']['high']}",
                             "fair": f"{v['fair']['low']} to {v['fair']['high']}", "put": v.get("put_strike_idea"),
                             "_new": was != kind, "_note": f"was {was}" if was and was != kind else ""})
        rows.sort(key=lambda r: not r["_new"])  # changes first, so the 40 row cap never hides them
        return rows[:40]  # keep the Drive copy readable
    vcols = [("ticker", "Ticker"), ("name", "Company"), ("price", "Price"), ("zone", "Buy zone"),
             ("fair", "Fair value"), ("put", "Put strike idea")]
    buy_now = vrows("Buy zone now")
    if new := [r["ticker"] for r in buy_now if r["_new"]]:
        news.append(f"Moved into the buy zone: {', '.join(new)}")
    out += ["<h2>Long term verdicts: in the buy zone now</h2>", table(vcols, buy_now),
            "<h2>Long term verdicts: accumulate on pullback</h2>", table(vcols, vrows("Accumulate on pullback"))]

    old_setups = old["setups.json"] or {}
    swing = mark(setups.get("swing", []), seen("setups.json", old_setups.get("swing", [])))
    csp = mark(setups.get("csp", []), seen("setups.json", old_setups.get("csp", [])))
    if new := [r["ticker"] for r in swing if r["_new"]]:
        news.append(f"New swing setups: {', '.join(new)}")
    if old["setups.json"] is not None:
        gone = sorted({r["ticker"] for r in old_setups.get("swing", [])} - {r["ticker"] for r in swing})
        if gone:
            news.append(f"Dropped off the swing list: {', '.join(gone)}")
    if new := [r["ticker"] for r in csp if r["_new"]]:
        news.append(f"New put ideas: {', '.join(new)}")
    ideas = mark(setups.get("csp_ideas", []), seen("setups.json", old_setups.get("csp_ideas", [])))
    if new := [r["ticker"] for r in ideas if r["_new"]]:
        news.append(f"New puts suggested by the brief: {', '.join(new)}")

    out += ["<h2>Swing setups</h2>",
            table([("ticker", "Ticker"), ("price", "Price"), ("entry", "Entry"), ("stop", "Stop"), ("risk_pct", "Risk %"),
                   ("target_2r", "Target 2R"), ("earnings", "Earnings")], swing),
            "<h2>Cash secured puts</h2>",
            table([("ticker", "Ticker"), ("expiration", "Expiry"), ("strike", "Strike"), ("premium", "Premium"),
                   ("annualized_pct", "Annualized %"), ("breakeven", "Breakeven"), ("earnings", "Earnings")], csp),
            "<h2>Put ideas from the brief</h2>",
            table([("ticker", "Ticker"), ("status", "Status"), ("expiration", "Expiry"), ("strike", "Strike"),
                   ("premium", "Premium"), ("annualized_pct", "Annualized %"), ("breakeven", "Breakeven"),
                   ("earnings", "Earnings"), ("why", "Why")], ideas)]

    if not have_old:
        box = "<p><i>No earlier snapshot to compare with, so nothing is marked new today.</i></p>"
    elif news:
        box = ("<ul>" + "".join(f'<li><span style="background-color:{HL}">{e(n)}</span></li>' for n in news) + "</ul>"
               f"<p><i>Rows marked {NEW}in the tables below are new since the last snapshot.</i></p>")
    else:
        box = "<p>No changes to the lists since the last snapshot.</p>"
    out[whats_new_at:whats_new_at] = [f'<h2><span style="background-color:{HL}">What\'s new today</span></h2>', box]

    return "<html><body>" + "\n".join(out) + "</body></html>"


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else None
    doc = build(day)
    path = ROOT / "output" / f"snapshot-{day or 'latest'}.html"
    path.parent.mkdir(exist_ok=True)
    path.write_text(doc)
    print(path)
