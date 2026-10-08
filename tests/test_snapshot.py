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
    doc = report.build()
    assert "1 of 40 market emails mattered" in doc
    assert "Set the buy stop." in doc and "<td>Act</td>" in doc
