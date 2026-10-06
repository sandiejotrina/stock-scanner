"""Daily snapshot of the dashboard as one HTML document, for archiving (Google Drive converts it to a Doc).

    python -m stockscan.report            writes output/snapshot-<date>.html and prints the path
"""

import html
import json
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


def table(cols: list[tuple[str, str]], rows: list[dict]) -> str:
    if not rows:
        return "<p><i>Nothing on the last run.</i></p>"
    head = "".join(f"<th>{e(label)}</th>" for _, label in cols)
    body = "".join("<tr>" + "".join(f"<td>{e(r.get(k))}</td>" for k, _ in cols) + "</tr>" for r in rows)
    return f'<table border="1" cellpadding="4" cellspacing="0"><tr>{head}</tr>{body}</table>'


def build(day: str | None = None) -> str:
    meta = _read("meta.json", {})
    briefs = meta.get("briefs", [])
    day = day or (briefs[0] if briefs else date.today().isoformat())
    b = _read(f"briefs/{day}.json", None) or {}
    lineup = _read("lineup.json", [])[:15]
    market = _read("market.json", {})
    insiders = _read("insiders.json", {}).get("by_ticker", [])
    congress = _read("congress.json", {})
    setups = _read("setups.json", {})

    out = [f"<h1>Money Trail daily snapshot, {e(day)}</h1>",
           f'<p>Dashboard: <a href="{SITE_URL}">{SITE_URL}</a>. Data refreshed {e(meta.get("generated"))} UTC.</p>',
           "<p><b>Research, not advice.</b> AI assisted research. Free data can be late or wrong.</p>"]

    if b:
        out += [f"<h2>Brief: {e(b.get('headline'))}</h2>",
                f"<p><b>Market:</b> {e(b.get('regime', {}).get('stance'))}. {e(b.get('summary'))}</p>"]
        levels = b.get("regime", {}).get("levels", [])
        out.append(table([("name", "Level"), ("value", "Value"), ("change_1w", "1 week")], levels))
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
    out += ["<h2>Lineup: top 15</h2>",
            table([("score", "Score"), ("ticker", "Ticker"), ("name", "Company"), ("reasons", "Why"),
                   ("chg_3m", "3 mo %"), ("themes", "Themes")], rows)]

    clusters = [r for r in insiders if r.get("cluster") or r.get("themes")][:15]
    out += ["<h2>Insider buying: clusters and theme names</h2>",
            table([("ticker", "Ticker"), ("company", "Company"), ("insiders", "Insiders"), ("top_role", "Most senior"),
                   ("total_value", "Total $"), ("last_trade", "Last trade")], clusters)]

    con = [{**r, "buyers": ", ".join(r["buyers"]), "leaders": ", ".join(r["leaders"])}
           for r in congress.get("by_ticker", []) if r.get("leaders") or r.get("net_buyers", 0) > 0][:15]
    out += [f"<h2>Congress: net buying (source: {e(', '.join(congress.get('sources', [])) or 'none')})</h2>",
            table([("ticker", "Ticker"), ("buyers", "Bought"), ("leaders", "Leader"), ("buy_amount_min", "At least $"),
                   ("last_filed", "Filed")], con)]

    verdicts = _read("verdicts.json", {})
    names = {t: places[0].get("name", "") for t, places in _read("tickers.json", {}).items() if places}
    def vrows(kind):
        rows = []
        for t, v in sorted(verdicts.items()):
            if v.get("verdict") == kind and v.get("zone"):
                rows.append({"ticker": t, "name": names.get(t, ""), "price": v.get("price"),
                             "zone": f"{v['zone']['low']} to {v['zone']['high']}",
                             "fair": f"{v['fair']['low']} to {v['fair']['high']}", "put": v.get("put_strike_idea")})
        return rows[:40]  # keep the Drive copy readable
    vcols = [("ticker", "Ticker"), ("name", "Company"), ("price", "Price"), ("zone", "Buy zone"),
             ("fair", "Fair value"), ("put", "Put strike idea")]
    out += ["<h2>Long term verdicts: in the buy zone now</h2>", table(vcols, vrows("Buy zone now")),
            "<h2>Long term verdicts: accumulate on pullback</h2>", table(vcols, vrows("Accumulate on pullback"))]

    out += ["<h2>Swing setups</h2>",
            table([("ticker", "Ticker"), ("price", "Price"), ("entry", "Entry"), ("stop", "Stop"), ("risk_pct", "Risk %"),
                   ("target_2r", "Target 2R"), ("earnings", "Earnings")], setups.get("swing", [])),
            "<h2>Cash secured puts</h2>",
            table([("ticker", "Ticker"), ("expiration", "Expiry"), ("strike", "Strike"), ("premium", "Premium"),
                   ("annualized_pct", "Annualized %"), ("breakeven", "Breakeven"), ("earnings", "Earnings")], setups.get("csp", []))]

    return "<html><body>" + "\n".join(out) + "</body></html>"


if __name__ == "__main__":
    day = sys.argv[1] if len(sys.argv) > 1 else None
    doc = build(day)
    path = ROOT / "output" / f"snapshot-{day or 'latest'}.html"
    path.parent.mkdir(exist_ok=True)
    path.write_text(doc)
    print(path)
