"""Decision cards: one card per live idea (a swing setup or a put), with everything needed to decide in one place.

The facts for one trade used to be spread across the brief, the Setups tables, the verdicts and the scorecard. A card
pulls them together: the verdict and chart checks, the plan with its reward for the risk, the earnings date, smart
money, the analyst view and phone alerts when the brief recorded them, and the strongest reason not to do it.
Every reason comes from a rule, so two cards with the same facts always say the same thing.
"""
from __future__ import annotations

from datetime import date

MIN_REWARD_RISK = 2.0
SWING_EARNINGS_DAYS = 14


def _days(d, today: date) -> int | None:
    try:
        return (date.fromisoformat(str(d)[:10]) - today).days
    except ValueError:
        return None


def _checks(v: dict | None) -> list[dict]:
    chart = (v or {}).get("chart") or {}
    return [{"name": k, "ok": ok} for k, ok in (chart.get("checks") or {}).items()]


def _against_swing(r: dict, v: dict | None, e_days: int | None, rr: float | None) -> list[str]:
    out = []
    if e_days is None:
        out.append("No earnings date found, so a report could land inside the trade.")
    elif 0 <= e_days <= SWING_EARNINGS_DAYS:
        out.append(f"Earnings in {e_days} days, inside a normal swing hold.")
    if (r.get("up_down_vol") or 0) < 1.2:
        out.append("Buyers are not clearly in control (up/down volume under 1.2).")
    if rr is not None and rr < MIN_REWARD_RISK:
        out.append(f"The target pays only {rr:.1f} times the risk.")
    if (r.get("risk_pct") or 0) >= 5:
        out.append(f"The stop is {r['risk_pct']}% below the entry, close to the 6% limit, so a normal pullback can stop it out.")
    if any(x.get("tone") == "down" for x in r.get("smart") or []):
        out.append("Smart money is selling: " + "; ".join(x["text"] for x in r["smart"] if x.get("tone") == "down") + ".")
    if v and v.get("verdict") in ("Wait", "Avoid", "Buyout pending"):
        why = " ".join(v.get("reasons") or [])
        out.append(f"The long term verdict is {v['verdict']}" + (f" ({why.rstrip('.')})" if why else "")
                   + ", so this is a short trade with a stop, not a stock to keep.")
    return out


def _against_put(r: dict, v: dict | None, e_days: int | None) -> list[str]:
    out = []
    dte = r.get("dte")
    if e_days is None:
        out.append("No earnings date found, so a report could land before expiry.")
    elif dte is not None and 0 <= e_days <= dte:
        out.append(f"Earnings in {e_days} days, before the {r.get('expiration')} expiry.")
    if not v or v.get("verdict") != "Buy zone now":
        out.append(f"The verdict is {(v or {}).get('verdict', 'missing')}, and her rule sells puts only on Buy zone now names.")
    failed = ((v or {}).get("chart") or {}).get("failed") or []
    if failed:
        out.append("Chart check failed: " + ", ".join(failed).lower() + ".")
    status = str(r.get("status") or "")
    if status.startswith("Check"):
        out.append(status.removeprefix("Check: ").capitalize() + ".")
    if any(x.get("tone") == "down" for x in r.get("smart") or []):
        out.append("Smart money is selling: " + "; ".join(x["text"] for x in r["smart"] if x.get("tone") == "down") + ".")
    return out


def build_cards(setups: dict, verdicts: dict, analyst: dict, alerts: list, today: date) -> list[dict]:
    alert_by: dict[str, list] = {}
    for a in alerts or []:
        alert_by.setdefault(str(a.get("ticker", "")).upper(), []).append(a)
    cards = []
    rows = ([("Swing", r) for r in setups.get("swing", [])] + [("Put idea", r) for r in setups.get("csp_ideas", [])]
            + [("Put", r) for r in setups.get("csp", [])])
    for kind, r in rows:
        t = r.get("ticker")
        if not t or (kind != "Swing" and r.get("strike") is None):
            continue
        v = verdicts.get(t)
        e_days = _days(r.get("earnings"), today)
        card = {"ticker": t, "kind": kind, "price": r.get("price"), "verdict": (v or {}).get("verdict"),
                "verdict_reasons": (v or {}).get("reasons", []), "zone": (v or {}).get("zone"), "checks": _checks(v),
                "earnings": r.get("earnings") if e_days is not None else None, "earnings_days": e_days,
                "smart": r.get("smart") or [], "themes": r.get("themes") or [],
                "analyst": analyst.get(t), "alerts": alert_by.get(t, [])}
        if kind == "Swing":
            risk = (r.get("entry") or 0) - (r.get("stop") or 0)
            rr = round((r["target_2r"] - r["entry"]) / risk, 1) if risk > 0 and r.get("target_2r") else None
            card["plan"] = {"entry": r.get("entry"), "stop": r.get("stop"), "target": r.get("target_2r"),
                            "risk_pct": r.get("risk_pct"), "reward_risk": rr, "confirm": r.get("volume_note")}
            against = _against_swing(r, v, e_days, rr)
            fallback = (f"No rule says no. What you risk: the stop is {r.get('risk_pct')}% below the {r.get('entry')} entry, "
                        "and the trade counts only on a close over the entry on 1.5 times normal volume.")
        else:
            card["plan"] = {"strike": r.get("strike"), "expiration": r.get("expiration"), "premium": r.get("premium"),
                            "annualized_pct": r.get("annualized_pct"), "breakeven": r.get("breakeven"),
                            "status": r.get("status")}
            against = _against_put(r, v, e_days)
            fallback = (f"No rule says no. What you risk: owning 100 shares at {r.get('breakeven')} if it falls through "
                        "the strike. Check the live bid before selling.")
        card["against"] = against
        card["top_reason_not"] = against[0] if against else fallback
        cards.append(card)
    return cards
