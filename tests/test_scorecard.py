from datetime import date

import pandas as pd

from stockscan.scorecard import grade, log_calls, summary


def bars(rows, start="2026-10-01"):
    idx = pd.bdate_range(start, periods=len(rows))
    return pd.DataFrame(rows, columns=["High", "Low", "Close"], index=idx)


def swing_bars(rows, base_days=55):
    """base_days of quiet trading at 100 on 1M shares a day, then rows of (open, high, low, close, volume)."""
    quiet = [(99.5, 100, 99, 99.5, 1e6)] * base_days
    idx = pd.bdate_range("2026-07-01", periods=base_days + len(rows))
    return pd.DataFrame(quiet + rows, columns=["Open", "High", "Low", "Close", "Volume"], index=idx)


def swing_call(df):
    return {"type": "swing", "ticker": "X", "date": str(df.index[54].date()), "entry": 101, "stop": 98, "target_2r": 107}


def test_swing_needs_a_close_over_entry_on_heavy_volume_and_a_close_at_target():
    df = swing_bars([(100, 103, 99, 100.5, 3e6),   # intraday over entry, closed under it: no trigger
                     (100, 102, 99, 101.5, 1.2e6),  # closed over entry on light volume: no trigger
                     (101, 103, 100, 102, 1.6e6),  # closed over entry on 1.6x volume: triggers, fill 102
                     (102, 108, 101, 105, 1e6),    # touched the target intraday only: still open
                     (105, 108, 104, 107.5, 1e6)])  # closed over the target: win
    g = grade(log_calls([], [swing_call(df)]), {"X": df}, None, date(2026, 10, 7))[0]
    assert g["status"] == "win" and g["fill"] == 102 and g["result_r"] == 1.38  # (107.5 - 102) / (102 - 98)
    assert g["triggered"] == str(df.index[57].date())


def test_swing_stop_never_triggered_and_late_confirmation():
    stop = swing_bars([(100, 102, 99, 101.5, 2e6), (100, 100, 97, 97.5, 1e6)])
    g = grade(log_calls([], [swing_call(stop)]), {"X": stop}, None, date(2026, 10, 3))[0]
    assert g["status"] == "loss" and g["result_r"] == -1.0
    intraday_only = swing_bars([(100, 103, 99, 100, 3e6)] * 25)
    g = grade(log_calls([], [swing_call(intraday_only)]), {"X": intraday_only}, None, date(2026, 11, 10))[0]
    assert g["status"] == "never_triggered"
    late = swing_bars([(104, 109, 103, 108, 2e6)])  # first heavy close over entry is already past the target
    g = grade(log_calls([], [swing_call(late)]), {"X": late}, None, date(2026, 10, 3))[0]
    assert g["status"] == "never_triggered" and "past the target" in g["note"]


def test_old_intraday_win_is_graded_again_under_her_rule():
    df = swing_bars([(100, 108, 99, 100, 3e6)])  # the old rule called this a win on the intraday high
    old = {**swing_call(df), "status": "win", "result_r": 2.0, "closed": str(df.index[55].date())}
    g = grade([old], {"X": df}, None, date(2026, 10, 3))[0]
    assert g["status"] == "waiting" and g["rule"] == "close_on_1.5x_volume" and "result_r" not in g


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
