from datetime import date

from stockscan.cards import build_cards

TODAY = date(2026, 11, 14)
SWING = {"ticker": "TMO", "price": 700.22, "entry": 729.03, "stop": 685.98, "target_2r": 815.13, "risk_pct": 5.9,
         "up_down_vol": 1.46, "earnings": "2027-01-28", "smart": [], "volume_note": "Buy over 729.03 only on 3.4M+ shares."}
WAIT = {"verdict": "Wait", "reasons": ["Price is 68% above the top of fair value."]}


def test_swing_card_has_plan_reward_and_the_strongest_reason_not():
    (c,) = build_cards({"swing": [SWING]}, {"TMO": WAIT}, {}, [{"ticker": "TMO", "level": 729.03, "kind": "trigger"}], TODAY)
    assert c["plan"]["reward_risk"] == 2.0 and c["earnings_days"] == 75 and len(c["alerts"]) == 1
    assert "close to the 6% limit" in c["top_reason_not"]  # wide stop is checked before the long term verdict
    assert any("long term verdict is Wait" in a for a in c["against"])


def test_swing_with_nothing_against_says_what_is_at_risk():
    clean = {**SWING, "risk_pct": 4.0}
    (c,) = build_cards({"swing": [clean]}, {"TMO": {"verdict": "Buy zone now"}}, {}, [], TODAY)
    assert c["against"] == [] and c["top_reason_not"].startswith("No rule says no")


def test_put_card_flags_earnings_before_expiry_and_a_non_buy_verdict():
    put = {"ticker": "APH", "strike": 72.5, "expiration": "2026-12-18", "dte": 34, "premium": 2.0, "breakeven": 70.5,
           "earnings": "2026-12-01", "status": "Check: thin market (open interest 26)"}
    (c,) = build_cards({"csp_ideas": [put]}, {"APH": {"verdict": "Buy zone, wait for the chart",
                                                       "chart": {"failed": ["Not sliding (down less than 8% in a month)"]}}},
                       {"APH": {"rating": "Buy", "target": 95}}, [], TODAY)
    assert c["top_reason_not"].startswith("Earnings in 17 days") and c["analyst"]["rating"] == "Buy"
    assert any("only on Buy zone now" in a for a in c["against"]) and any("Thin market" in a for a in c["against"])


def test_missing_earnings_date_is_a_reason_not():
    (c,) = build_cards({"swing": [{**SWING, "earnings": "CHECK"}]}, {}, {}, [], TODAY)
    assert c["earnings"] is None and c["top_reason_not"].startswith("No earnings date found")


def test_confirmed_break_down_blocks_a_put():
    from datetime import date
    from stockscan.cards import build_cards
    setups = {"swing": [], "csp": [{"ticker": "ABC", "price": 50, "strike": 45, "dte": 35, "expiration": "2026-12-18",
                                    "earnings": "2027-01-30", "premium": 1.0, "breakeven": 44, "status": "Passes"}]}
    verdicts = {"ABC": {"verdict": "Buy zone now", "chart": {"failed": []}}}
    ranges = {"breaks_down": [{"ticker": "ABC", "level": 48.1, "rvol": 2.1, "date": "2026-11-13",
                               "confirmed": True, "holding": True}]}
    card = build_cards(setups, verdicts, {}, [], date(2026, 11, 15), ranges)[0]
    assert card["top_reason_not"].startswith("It closed under its range (48.1)")
    weak = {"breaks_down": [{**ranges["breaks_down"][0], "confirmed": False}]}
    assert "range" not in build_cards(setups, verdicts, {}, [], date(2026, 11, 15), weak)[0]["top_reason_not"]


def test_confirmed_break_down_after_a_drop_blocks_a_put():
    from datetime import date
    from stockscan.cards import build_cards
    setups = {"swing": [], "csp": [{"ticker": "ABC", "price": 50, "strike": 45, "dte": 35, "expiration": "2026-12-18",
                                    "earnings": "2027-01-30", "premium": 1.0, "breakeven": 44, "status": "Passes"}]}
    verdicts = {"ABC": {"verdict": "Buy zone now", "chart": {"failed": []}}}
    ranges = {"breaks_down": [], "after_drop": {"breaks_down": [{"ticker": "ABC", "level": 47.0, "rvol": 1.8,
              "date": "2026-11-13", "confirmed": True, "holding": True}]}}
    card = build_cards(setups, verdicts, {}, [], date(2026, 11, 15), ranges)[0]
    assert card["top_reason_not"].startswith("It closed under its range (47.0)")
