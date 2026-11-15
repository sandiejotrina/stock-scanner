import numpy as np
import pandas as pd

from stockscan.ranges import find_break, scan_ranges, watch_levels


def frame(closes, volumes=None, spread=0.4):
    idx = pd.bdate_range("2026-01-01", periods=len(closes))
    c = np.array(closes, dtype=float)
    v = np.array(volumes if volumes is not None else [1_000_000] * len(c), dtype=float)
    return pd.DataFrame({"Open": c, "High": c + spread, "Low": c - spread, "Close": c, "Volume": v}, index=idx)


def trend_then_range(last=None, last_vol=1_000_000, n_range=25):
    """60 days of a wide swing (high Bollinger width), then a tight range around 100, then an optional last bar."""
    wide = [100 + 8 * np.sin(i / 3) for i in range(60)]
    tight = [100 + 0.6 * np.sin(i) for i in range(n_range)]
    closes = wide + tight + ([last] if last is not None else [])
    vols = [1_000_000] * (len(closes) - 1) + [last_vol]
    return frame(closes, vols)


def test_break_up_on_heavy_volume_is_confirmed():
    b = find_break(trend_then_range(last=104, last_vol=2_000_000))
    assert b["side"] == "up" and b["confirmed"] and b["holding"] and b["days_ago"] == 0
    assert b["level"] == b["range_high"] and b["rvol"] >= 1.5
    assert "Confirmed" in b["note"]


def test_break_up_on_light_volume_is_weak():
    b = find_break(trend_then_range(last=104, last_vol=1_100_000))
    assert b["side"] == "up" and not b["confirmed"]
    assert "light volume" in b["note"]


def test_break_down_is_a_warning_not_a_short():
    b = find_break(trend_then_range(last=96, last_vol=2_500_000))
    assert b["side"] == "down" and b["confirmed"] and b["level"] == b["range_low"]
    assert "Do not sell puts" in b["note"]
    assert "short" not in b["note"].lower()


def test_close_back_inside_is_a_failed_break():
    df = trend_then_range(last=104, last_vol=2_000_000)
    df = pd.concat([df, frame([100.2], spread=0.4).set_axis([df.index[-1] + pd.offsets.BDay()])])
    b = find_break(df)
    assert b["side"] == "up" and not b["holding"] and "Failed" in b["note"]


def test_wide_range_is_not_a_range():
    closes = [100 + 8 * np.sin(i / 3) for i in range(90)] + [115]
    assert find_break(frame(closes)) is None
    assert watch_levels(frame(closes)) is None


def test_inside_a_tight_range_gives_alert_levels():
    w = watch_levels(trend_then_range())
    assert w is not None and w["low"] < w["price"] < w["high"]
    assert w["volume_needed"] == 1_500_000


def test_scan_sorts_caps_and_skips_thin_names():
    prices = {f"T{i}": trend_then_range(n_range=25 + (i % 5)) for i in range(14)}
    prices["UP"] = trend_then_range(last=104, last_vol=2_000_000)
    prices["DN"] = trend_then_range(last=96, last_vol=2_000_000)
    thin = trend_then_range()
    thin["Volume"] = 1_000
    prices["THIN"] = thin
    out = scan_ranges(prices, {"max_per_side": 10}, "2026-11-13")
    assert [r["ticker"] for r in out["breaks_up"]] == ["UP"]
    assert [r["ticker"] for r in out["breaks_down"]] == ["DN"]
    assert len(out["watch_up"]) == 10 and len(out["watch_down"]) == 10
    tickers = {r["ticker"] for r in out["watch_up"] + out["watch_down"]}
    assert not tickers & {"UP", "DN", "THIN"}
    dist = [r["to_high_pct"] for r in out["watch_up"]]
    assert dist == sorted(dist)


# ---------- bases after a big drop ----------

from stockscan.ranges import drop_base_watch, find_drop_break


def crash_then_box(box_days=8, last=None, last_vol=1_000_000, crash_vol=6_000_000, drop=0.12):
    """250 calm days near 100, one crash day, then a box near the crash close, then an optional last bar."""
    calm = [100 + 0.5 * np.sin(i / 4) for i in range(250)]
    low = 100 * (1 - drop)
    box = [low + 1.5 + 1.2 * np.sin(i) for i in range(box_days)]
    closes = calm + [low] + box + ([last] if last is not None else [])
    vols = [1_000_000] * 250 + [crash_vol] + [1_000_000] * box_days + ([last_vol] if last is not None else [])
    return frame(closes, vols)


def test_box_after_a_crash_is_found_even_without_a_squeeze():
    df = crash_then_box()
    assert watch_levels(df) is None  # the plain range test misses it: the crash is in the window
    w = drop_base_watch(df)
    assert w["drop_pct"] <= -8 and w["base_days"] == 8 and w["low"] < w["price"] < w["high"]


def test_break_up_out_of_the_box_uses_volume_without_the_crash_day():
    df = crash_then_box(last=95, last_vol=1_600_000)
    b = find_drop_break(df)
    # 1.6M against a normal of 1M is confirmed; counting the 6M crash day would have made it look light
    assert b["side"] == "up" and b["confirmed"] and b["rvol"] >= 1.5


def test_break_down_out_of_the_box_and_downtrend_tag():
    df = crash_then_box(last=84, last_vol=2_000_000)
    b = find_drop_break(df)
    assert b["side"] == "down" and b["confirmed"] and "Do not sell puts" in b["note"]
    assert b["context"] and b["context"].startswith("Bounce inside a downtrend")


def test_too_few_days_after_the_crash_is_not_a_box_yet():
    assert drop_base_watch(crash_then_box(box_days=3)) is None


def test_small_drop_is_not_a_crash():
    assert drop_base_watch(crash_then_box(drop=0.05)) is None


def test_scan_reports_after_drop_section():
    out = scan_ranges({"BOX": crash_then_box(), "UP": crash_then_box(last=95, last_vol=1_600_000)}, {}, "2026-11-13")
    ad = out["after_drop"]
    assert [r["ticker"] for r in ad["bases"]] == ["BOX"]
    assert [r["ticker"] for r in ad["breaks_up"]] == ["UP"]
