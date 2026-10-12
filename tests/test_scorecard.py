from datetime import date

import pandas as pd

from stockscan.scorecard import grade, log_calls, summary


def bars(rows, start="2026-10-01"):
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, columns=["High", "Low", "Close"], index=idx)


def test_swing_triggers_then_hits_target():
    df = bars([(100, 98, 99), (101, 99, 100), (106, 100, 105), (112, 104, 111)])
    log = log_calls([], [{"type": "swing", "ticker": "X", "date": "2026-10-01", "entry": 101, "stop": 98, "target_2r": 107}])
    g = grade(log, {"X": df}, None, date(2026, 10, 7))[0]
    assert g["status"] == "win" and g["result_r"] == 2.0


def test_swing_stop_first_and_never_triggered():
    df = bars([(100, 98, 99), (102, 97, 98)])
    stop = grade([{"type": "swing", "ticker": "X", "date": "2026-10-01", "entry": 101, "stop": 98, "target_2r": 107, "status": "waiting"}], {"X": df}, None, date(2026, 10, 3))[0]
    assert stop["status"] == "loss"
    flat = bars([(100, 99, 99.5)] * 25)
    never = grade([{"type": "swing", "ticker": "X", "date": "2026-10-01", "entry": 101, "stop": 98, "target_2r": 107, "status": "waiting"}], {"X": flat}, None, date(2026, 11, 10))[0]
    assert never["status"] == "never_triggered"


def test_put_kept_or_assigned_at_expiry():
    df = bars([(30, 28, 29)] * 10)
    c = {"type": "put", "ticker": "P", "date": "2026-10-01", "strike": 27, "expiration": "2026-10-09", "premium": 0.5, "status": "open"}
    assert grade([c], {"P": df}, None, date(2026, 10, 20))[0]["status"] == "win"
    low = bars([(26, 24, 25)] * 10)
    a = grade([c], {"P": low}, None, date(2026, 10, 20))[0]
    assert a["status"] == "assigned" and a["result_pct"] < 0


def test_long_vs_spy_and_no_double_logging():
    up = bars([(0, 0, 100 + i) for i in range(30)])
    spy = bars([(0, 0, 100)] * 30)
    log = log_calls([], [{"type": "long", "ticker": "L", "date": "2026-10-01"}])
    log = log_calls(log, [{"type": "long", "ticker": "L", "date": "2026-10-02"}])
    assert len(log) == 1
    g = grade(log, {"L": up}, spy, date(2026, 11, 20))[0]
    assert g["ret_5d"] == 5.0 and g["vs_spy_5d"] == 5.0 and g["status"] == "open"  # 60 day horizon not reached
    assert summary([g])["long"]["beat_spy_5d"] == {"right": 1, "of": 1}
