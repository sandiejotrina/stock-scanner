"""Drive snapshot: the filtered inbox section shows up when the brief has one."""

import json

from stockscan import report


def test_snapshot_includes_filtered_inbox(tmp_path, monkeypatch):
    (tmp_path / "briefs").mkdir()
    brief = {"date": "2026-10-08", "headline": "H", "summary": "S", "regime": {}, "signals": [], "calendar": [],
             "actions": {}, "inbox": {"scanned": 40, "kept": 1, "skipped": "39 pitches",
                                      "items": [{"priority": "act", "source": "TrendSpider: The Entry Timer",
                                                 "tickers": ["MSFT"], "what": "Fired on a swing name.",
                                                 "action": "Set the buy stop."}]}}
    (tmp_path / "briefs" / "2026-10-08.json").write_text(json.dumps(brief))
    (tmp_path / "meta.json").write_text(json.dumps({"briefs": ["2026-10-08"]}))
    monkeypatch.setattr(report, "DATA", tmp_path)
    doc = report.build(previous=lambda name, day: None)
    assert "1 of 40 market emails mattered" in doc
    assert "Set the buy stop." in doc and "<td>Act</td>" in doc


def test_snapshot_highlights_what_changed_since_last_snapshot(tmp_path, monkeypatch):
    (tmp_path / "meta.json").write_text(json.dumps({"briefs": []}))
    (tmp_path / "setups.json").write_text(json.dumps({"swing": [{"ticker": "MSFT"}, {"ticker": "ZBRA"}], "csp": []}))
    (tmp_path / "verdicts.json").write_text(json.dumps({
        "GILD": {"verdict": "Buy zone now", "price": 1, "zone": {"low": 1, "high": 2}, "fair": {"low": 1, "high": 2}}}))
    monkeypatch.setattr(report, "DATA", tmp_path)
    before = {"setups.json": {"swing": [{"ticker": "MSFT"}, {"ticker": "ANET"}], "csp": []},
              "verdicts.json": {"GILD": {"verdict": "Wait"}}}
    doc = report.build("2026-10-08", previous=lambda name, day: before.get(name))
    assert "New swing setups: ZBRA" in doc and "Dropped off the swing list: ANET" in doc
    assert "Moved into the buy zone: GILD" in doc and "(was Wait)" in doc
    assert doc.count("<b>NEW</b>") == 3  # ZBRA row, GILD row, and the legend


def test_snapshot_marks_nothing_without_an_earlier_snapshot(tmp_path, monkeypatch):
    (tmp_path / "meta.json").write_text(json.dumps({"briefs": []}))
    (tmp_path / "setups.json").write_text(json.dumps({"swing": [{"ticker": "MSFT"}], "csp": []}))
    monkeypatch.setattr(report, "DATA", tmp_path)
    doc = report.build("2026-10-08", previous=lambda name, day: None)
    assert "nothing is marked new" in doc and "<b>NEW</b>" not in doc
