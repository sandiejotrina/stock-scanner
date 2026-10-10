from datetime import datetime, timezone

from stockscan.changes import OLD, is_new, track


def at(s):
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def test_first_run_marks_nothing_new():
    seen, new = track({}, {"lineup:MSFT": "1"}, at("2026-10-06T21:45"))
    assert seen["items"]["lineup:MSFT"]["first"] == OLD
    assert [k for k in new if k != "_gone"] == []


def test_evening_add_is_new_next_morning_and_gone_a_day_later():
    seen, _ = track({}, {"swing:A": "1"}, at("2026-10-05T21:45"))  # Monday
    seen, new = track(seen, {"swing:A": "1", "swing:B": "1"}, at("2026-10-06T21:45"))
    assert "swing:B" in new and "swing:A" not in new
    _, new = track(seen, {"swing:A": "1", "swing:B": "1"}, at("2026-10-07T12:51"))
    assert "swing:B" in new
    _, new = track(seen, {"swing:A": "1", "swing:B": "1"}, at("2026-10-08T12:51"))
    assert "swing:B" not in new


def test_friday_add_still_new_monday_morning():
    seen, _ = track({}, {"x": "1"}, at("2026-10-08T21:45"))
    seen, _ = track(seen, {"x": "1", "csp:Z": "1"}, at("2026-10-09T21:45"))  # Friday
    assert is_new(seen["items"]["csp:Z"]["first"], at("2026-10-12T12:51"))
    assert not is_new(seen["items"]["csp:Z"]["first"], at("2026-10-13T12:51"))


def test_value_change_keeps_was_and_drops_are_listed():
    seen, _ = track({}, {"verdict:MU": "Wait", "swing:A": "1"}, at("2026-10-06T21:45"))
    _, new = track(seen, {"verdict:MU": "Buy zone now"}, at("2026-10-07T21:45"))
    assert new["verdict:MU"]["was"] == "Wait"
    assert new["_gone"] == ["swing:A"]
