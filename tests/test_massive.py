from datetime import date

import pandas as pd

from stockscan import massive


class FakeHttp:
    """Answers like Massive's grouped daily bars. Oct 29 is the session Yahoo missed."""

    def __init__(self, days):
        self.days, self.calls = days, []

    def get(self, url, params, timeout):
        day = url.rsplit("/", 1)[-1]
        self.calls.append(day)
        rows = self.days.get(day, [])

        class R:
            status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"results": rows}
        return R()


def yahoo(last_day):
    idx = pd.bdate_range(end=last_day, periods=3)
    return pd.DataFrame({"Open": 1.0, "High": 1.0, "Low": 1.0, "Close": [1.0, 2.0, 3.0], "Volume": 100.0}, index=idx)


def test_fills_the_close_yahoo_missed_and_skips_foreign_and_holidays():
    bar = lambda t, c: {"T": t, "o": c, "h": c + 1, "l": c - 1, "c": c, "v": 5e6}
    http = FakeHttp({"2026-10-29": [bar("SPY", 600.0), bar("BRK.B", 480.0)], "2026-10-30": []})
    prices = {"SPY": yahoo("2026-10-28"), "BRK-B": yahoo("2026-10-28"), "6857.T": yahoo("2026-10-28")}
    out, filled = massive.fill_latest(prices, date(2026, 10, 30), "k", http)
    assert filled == ["2026-10-29"] and http.calls == ["2026-10-29", "2026-10-30"]  # Oct 30 came back empty
    assert out["SPY"].index[-1] == pd.Timestamp("2026-10-29") and out["SPY"]["Close"].iloc[-1] == 600.0
    assert out["SPY"]["Volume"].iloc[-1] == 5e6 and list(out["SPY"].columns) == ["Open", "High", "Low", "Close", "Volume"]
    assert out["BRK-B"]["Close"].iloc[-1] == 480.0
    assert out["6857.T"].index[-1] == pd.Timestamp("2026-10-28")  # Tokyo is not in the US bars


def test_nothing_to_fill_when_yahoo_is_current():
    http = FakeHttp({})
    out, filled = massive.fill_latest({"SPY": yahoo("2026-10-30")}, date(2026, 10, 30), "k", http)
    assert filled == [] and http.calls == []
    assert massive.missing_sessions(date(2026, 10, 23), date(2026, 11, 2)) == [
        date(2026, 10, 27), date(2026, 10, 28), date(2026, 10, 29), date(2026, 10, 30), date(2026, 11, 2)]
    # weekdays only, and at most the newest five sessions
