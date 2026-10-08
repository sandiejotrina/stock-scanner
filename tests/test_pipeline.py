"""Offline tests for the dashboard pipeline: insiders, Congress, lineup scoring and the full build."""

import json
from datetime import date, timedelta

import pandas as pd

from stockscan import congress, insiders, site_data
from test_scanner import FakeSource, breakout_stock, downtrend_stock, spy

OPENINSIDER_HTML = """
<table class="tinytable"><thead><tr>
<th>X</th><th>Filing Date</th><th>Trade Date</th><th>Ticker</th><th>Company Name</th><th>Insider Name</th>
<th>Title</th><th>Trade Type</th><th>Price</th><th>Qty</th><th>Owned</th><th>ΔOwn</th><th>Value</th></tr></thead>
<tbody>
<tr><td></td><td>2026-10-01 16:05:01</td><td>2026-09-29</td><td>VRT</td><td>Vertiv</td><td>Doe Jane</td><td>CEO</td><td>P - Purchase</td><td>$120.50</td><td>+10,000</td><td>50,000</td><td>+25%</td><td>+$1,205,000</td></tr>
<tr><td></td><td>2026-10-02 16:05:01</td><td>2026-09-30</td><td>VRT</td><td>Vertiv</td><td>Roe Rick</td><td>Dir</td><td>P - Purchase</td><td>$121.00</td><td>+1,000</td><td>9,000</td><td>+12%</td><td>+$121,000</td></tr>
<tr><td></td><td>2026-10-02 16:05:01</td><td>2026-09-30</td><td>XYZ</td><td>Xyz Corp</td><td>Lee Al</td><td>Dir</td><td>S - Sale</td><td>$10.00</td><td>-1,000</td><td>0</td><td>-100%</td><td>-$10,000</td></tr>
</tbody></table>"""

PTR_TEXT = """ID Owner Asset Transaction Type Date Notification Date Amount Cap. Gains > $200?
SP Vertiv Holdings Co (VRT) [ST] P 09/02/2026 09/20/2026 $15,001 - $50,000
FILING STATUS: New
Apple Inc. (AAPL) [ST] S (partial) 08/28/2026 09/20/2026 $1,001 - $15,000
US Treasury Bill [GS] P 08/28/2026 09/20/2026 $50,001 - $100,000"""


def test_openinsider_keeps_only_purchases_and_finds_cluster():
    rows = insiders.parse_openinsider(OPENINSIDER_HTML)
    assert set(rows["ticker"]) == {"VRT"}
    summary = insiders.summarize(rows)
    assert summary[0]["ticker"] == "VRT" and summary[0]["cluster"] and summary[0]["insiders"] == 2
    assert summary[0]["total_value"] == 1326000 and summary[0]["top_role"] == "CEO"


def test_house_ptr_parsing_reads_stock_lines_only():
    filing = {"First": "Jane", "Last": "Smith", "Year": "2026", "DocID": "20031234", "filed": "2026-09-21"}
    rows = congress.parse_house_ptr(PTR_TEXT, filing)
    assert [(r["ticker"], r["type"]) for r in rows] == [("VRT", "buy"), ("AAPL", "sell")]
    assert rows[0]["owner"] == "SP" and rows[0]["lag_days"] == 19 and rows[0]["amount_low"] == 15001


def test_leader_matching_avoids_common_names():
    assert congress.leader_role("Mike Johnson") == "Speaker of the House"
    assert congress.leader_role("Hank Johnson") is None
    assert congress.leader_role("Chuck Schumer") == "Senate Minority Leader"


def test_lineup_rewards_alignment_and_punishes_downtrend():
    places = [{"theme_name": "AI power", "layer": "Cooling", "name": "Vertiv", "exposure": "pure play", "chokepoint": True}]
    good = site_data.lineup_score(
        "VRT", places, {"VRT": {"trend": "uptrend", "vs_spy_3m": 5, "breakout_setup": True}},
        {"VRT": {"cluster": True, "insiders": 2, "top_role": "CEO"}},
        {"VRT": {"leaders": ["Mike Johnson (Speaker of the House)"], "net_buyers": 1, "buyers": ["Mike Johnson"]}}, set(),
    )
    bad = site_data.lineup_score("VRT", places, {"VRT": {"trend": "downtrend", "vs_spy_3m": -5, "breakout_setup": False}}, {}, {}, set())
    assert good["score"] > 15 > bad["score"]
    assert "Downtrend" in [r["text"] for r in bad["reasons"]]


def test_full_build_offline_with_fake_sources(tmp_path, monkeypatch):
    research = tmp_path / "research"
    (research / "themes").mkdir(parents=True)
    (research / "briefs").mkdir()
    theme = {"id": "t1", "name": "Test theme", "thesis": "x", "layers": [{"name": "L1", "why": "", "bottleneck": "high",
             "companies": [{"ticker": "BRK", "name": "Breakout Co", "role": "r", "exposure": "pure play", "chokepoint": True, "us_tradable": True},
                           {"ticker": "3110.T", "name": "Foreign Co", "role": "r", "exposure": "major", "chokepoint": True, "us_tradable": False}]}]}
    (research / "themes" / "t1.json").write_text(json.dumps(theme))
    (research / "briefs" / "2026-10-05.json").write_text(json.dumps({"date": "2026-10-05", "signals": []}))
    out = tmp_path / "data"
    monkeypatch.setattr(site_data, "RESEARCH", research)
    monkeypatch.setattr(site_data, "OUT", out)

    from stockscan import data as yahoo, runner
    fake = FakeSource()
    frames = {"BRK": breakout_stock(), "DOWN": downtrend_stock(), "SPY": spy(), "3110.T": breakout_stock()}
    monkeypatch.setattr(yahoo, "load_prices", lambda syms: {s: frames[s] for s in syms if s in frames})
    monkeypatch.setattr(yahoo, "company_events", fake.company_events)
    monkeypatch.setattr(yahoo, "option_chain", fake.option_chain)
    monkeypatch.setattr(runner, "load_universe", lambda: ["DOWN"])
    monkeypatch.setattr(insiders, "fetch", lambda **k: insiders.summarize(insiders.parse_openinsider(OPENINSIDER_HTML)))
    monkeypatch.setattr(congress, "fetch", lambda **k: {"sources": ["fake"], "errors": [], "trades": [], "by_ticker": []})

    meta = site_data.build()
    assert meta["errors"] == [] and meta["briefs"] == ["2026-10-05"]
    market = json.loads((out / "market.json").read_text())
    assert {"BRK", "DOWN", "3110.T"} <= set(market)
    setups = json.loads((out / "setups.json").read_text())
    assert [r["ticker"] for r in setups["swing"]] == ["BRK"]  # foreign names never become trade ideas
    lineup = json.loads((out / "lineup.json").read_text())
    assert lineup[0]["ticker"] in {"BRK", "3110.T"} and lineup[0]["chokepoint"]
    assert json.loads((out / "themes.json").read_text())[0]["pct_uptrend"] == 100


SENATE_PTR = """<table class="table"><thead><tr><th>#</th><th>Transaction Date</th><th>Owner</th><th>Ticker</th>
<th>Asset Name</th><th>Asset Type</th><th>Type</th><th>Amount</th><th>Comment</th></tr></thead><tbody>
<tr><td>1</td><td>09/10/2026</td><td>Spouse</td><td><a href="#">VRT</a></td><td>Vertiv Holdings</td><td>Stock</td>
<td>Purchase</td><td>$15,001 - $50,000</td><td>--</td></tr>
<tr><td>2</td><td>09/11/2026</td><td>Self</td><td>--</td><td>US Treasury Note</td><td>Other Securities</td>
<td>Purchase</td><td>$50,001 - $100,000</td><td>--</td></tr>
<tr><td>4</td><td>09/11/2026</td><td>Self</td><td>--</td><td>Some Fund</td><td>Stock</td>
<td>Sale (Full)</td><td>$1,001 - $15,000</td><td>--</td></tr>
<tr><td>3</td><td>09/12/2026</td><td>Self</td><td>AAPL</td><td>Apple Inc.</td><td>Stock</td>
<td>Sale (Partial)</td><td>$1,001 - $15,000</td><td>--</td></tr></tbody></table>"""


def test_senate_ptr_parsing_keeps_stock_trades():
    filing = {"first": "John", "last": "Thune", "filed": "2026-09-30", "url": "https://efdsearch.senate.gov/x"}
    rows = congress.parse_senate_ptr(SENATE_PTR, filing)
    assert [(r["ticker"], r["type"], r["owner"]) for r in rows] == [("VRT", "buy", "SP"), ("AAPL", "sell", "")]
    assert rows[0]["chamber"] == "Senate" and rows[0]["lag_days"] == 20
    assert rows[0]["leader"] == "Senate Majority Leader"


def test_fetch_combines_house_and_senate_when_quiver_fails(monkeypatch):
    def boom(days):
        raise RuntimeError("401")
    monkeypatch.setattr(congress, "fetch_quiver", boom)
    monkeypatch.setattr(congress, "fetch_house", lambda d: [congress._row("House Clerk", "A B", "House", "", "VRT", "P", "2026-09-01", "2026-09-20", "$1,001 - $15,000")])
    monkeypatch.setattr(congress, "fetch_senate", lambda d: [congress._row("Senate eFD", "C D", "Senate", "", "VRT", "Purchase", "2026-09-02", "2026-09-21", "$1,001 - $15,000")])
    out = congress.fetch(60)
    assert len(out["trades"]) == 2 and out["by_ticker"][0]["buyers"] == ["A B", "C D"]
    assert out["sources"] == ["House Clerk (1 trades)", "Senate eFD (1 trades)"]


def test_put_ideas_are_quoted_with_reasons_not_dropped():
    from datetime import date as _d
    import numpy as np
    import pandas as pd
    from stockscan.runner import load_settings, quote_put_ideas

    idx = pd.bdate_range(end="2026-10-07", periods=260)
    close = pd.Series(np.linspace(100, 140, len(idx)), index=idx)
    df = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 2e6})

    class Src:
        def option_chain(self, t, lo, hi, today):
            puts = pd.DataFrame({"strike": [120.0, 125.0, 130.0], "bid": [1.0, 1.5, 2.0], "ask": [1.05, 1.6, 2.1],
                                 "openInterest": [500, 500, 500], "impliedVolatility": [0.3, 0.3, 0.3]})
            return {"expiration": "2026-11-20", "dte": 43, "puts": puts, "calls": puts}

        def company_events(self, t):
            return {"earnings": _d(2026, 10, 30), "ex_dividend": None, "market_cap": 1e11}

    rows = quote_put_ideas([{"ticker": "gild", "strike": 126, "added": "2026-10-08"}, {"ticker": "NOPE"}],
                           {"GILD": df}, load_settings(), Src(), _d(2026, 10, 8))
    g, n = rows
    assert g["ticker"] == "GILD" and g["strike"] == 125.0 and g["premium"] == 1.55
    assert "earnings before expiry" in g["status"]
    assert n["status"].startswith("No price data")


def test_vix_status_zones_and_percentile():
    from datetime import date as _d
    import numpy as np
    import pandas as pd
    from stockscan.site_data import vix_status

    idx = pd.bdate_range(end="2026-10-07", periods=300)
    calm = vix_status(pd.DataFrame({"Close": np.r_[np.full(299, 20.0), 13.0]}, index=idx), _d(2026, 10, 8))
    assert calm["zone"] == "Calm" and calm["pct_1y"] == 0 and "thin" in calm["puts"]
    fear = vix_status(pd.DataFrame({"Close": np.r_[np.linspace(12, 25, 299), 35.0]}, index=idx), _d(2026, 10, 8))
    assert fear["zone"] == "Fear" and fear["pct_1y"] == 100 and len(fear["history"]) == 60


def test_put_idea_without_live_quotes_uses_last_trade_and_says_so():
    from datetime import date as _d
    import numpy as np
    import pandas as pd
    from stockscan.runner import load_settings, quote_put_ideas

    idx = pd.bdate_range(end="2026-10-07", periods=260)
    close = pd.Series(np.linspace(100, 140, len(idx)), index=idx)
    df = pd.DataFrame({"Open": close, "High": close * 1.01, "Low": close * 0.99, "Close": close, "Volume": 2e6})

    class Src:
        def option_chain(self, t, lo, hi, today):
            puts = pd.DataFrame({"strike": [120.0, 125.0], "bid": [0.0, 0.0], "ask": [0.0, 0.0], "lastPrice": [1.1, 1.6],
                                 "openInterest": [900, 900], "impliedVolatility": [0.3, 0.3]})
            return {"expiration": "2026-11-20", "dte": 43, "puts": puts, "calls": puts}

        def company_events(self, t):
            return {"earnings": _d(2026, 12, 1), "ex_dividend": None, "market_cap": 1e11}

    (g,) = quote_put_ideas([{"ticker": "GILD", "strike": 126}], {"GILD": df}, load_settings(), Src(), _d(2026, 10, 8))
    assert g["strike"] == 125.0 and g["premium"] == 1.6 and "last trade" in g["status"]
