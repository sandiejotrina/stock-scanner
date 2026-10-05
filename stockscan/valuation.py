"""Long term verdicts: is this a business worth owning, what is a fair price, and is now a good time.

Rules based and the same for every stock, so the dashboard can show exactly why each verdict was given.

1. Quality: five checks on the business. Profitable companies need 3 of 5. Early stage companies
   (no forward earnings yet) need fast growth and healthy gross margins instead.
2. Fair value range:
   - Profitable: forward EPS x a fair P/E, where the fair P/E is about 1.5x the growth rate
     (the lower of revenue and earnings growth, a PEG of 1.5), kept between 12 and 35.
   - Early stage: fair EV/sales from the growth rate, kept between 2 and 15, turned back into a share price.
   - Chokepoints and pure plays, the core of the follow the money thesis, get a 20% premium.
3. Buy zone: where fair value meets chart support (the 50 and 200 day averages).
4. Verdict: Buy zone now, Accumulate on pullback, Wait, Avoid, or Not enough data.
"""

import math

QUALITY_MIN_PROFITABLE = 3


def _num(x):
    try:
        x = float(x)
        return None if math.isnan(x) or math.isinf(x) else x
    except (TypeError, ValueError):
        return None


def _clamp(x, lo, hi):
    return max(lo, min(hi, x))


def quality(f: dict) -> dict:
    """Five plain checks. Each is True, False or None (no data)."""
    rev_g, eps_g = _num(f.get("revenue_growth")), _num(f.get("earnings_growth"))
    op_m, gross_m = _num(f.get("operating_margin")), _num(f.get("gross_margin"))
    fcf, debt, ebitda, de = _num(f.get("fcf")), _num(f.get("total_debt")), _num(f.get("ebitda")), _num(f.get("debt_to_equity"))

    if debt is not None and ebitda and ebitda > 0:
        debt_ok = debt <= 3 * ebitda
    elif de is not None:
        debt_ok = de < 100
    else:
        debt_ok = None

    checks = {
        "Revenue growing": None if rev_g is None else rev_g > 0.05,
        "Healthy margins": (None if op_m is None and gross_m is None
                            else (op_m is not None and op_m > 0.10) or (gross_m is not None and gross_m > 0.50)),
        "Free cash flow positive": None if fcf is None else fcf > 0,
        "Debt manageable": debt_ok,
        "Earnings growing": None if eps_g is None else eps_g > 0,
    }
    known = [v for v in checks.values() if v is not None]
    return {"checks": checks, "passed": sum(1 for v in known if v), "known": len(known)}


def fair_value(f: dict, premium: bool) -> dict | None:
    """Fair value range per share, or None when the data is not there."""
    fwd_eps = _num(f.get("forward_eps"))
    rev_g = _num(f.get("revenue_growth")) or 0.0
    eps_g = _num(f.get("earnings_growth"))
    bump = 1.2 if premium else 1.0

    price = _num(f.get("price"))
    # Barely profitable companies (forward P/E above 80) are valued on sales: tiny earnings x a P/E means nothing.
    tiny_earnings = fwd_eps and fwd_eps > 0 and price and price / fwd_eps > 80
    if fwd_eps and fwd_eps > 0 and not tiny_earnings:
        # Conservative on purpose: the lower of revenue and earnings growth, since one strong year
        # (often near a cycle peak) should not set the price for the long term.
        growth = [g for g in (rev_g, eps_g) if g is not None]
        g_pct = _clamp(100 * min(growth), 3, 30) if growth else 8
        fair_pe = _clamp(1.5 * g_pct, 12, 35) * bump
        mid = fwd_eps * fair_pe
        return {"method": f"Forward EPS x fair P/E of {fair_pe:.0f}", "low": round(mid * 0.85, 2),
                "mid": round(mid, 2), "high": round(mid * 1.15, 2), "stage": "profitable"}

    revenue, shares = _num(f.get("revenue")), _num(f.get("shares"))
    if revenue and shares and revenue > 0 and shares > 0:
        cash, debt = _num(f.get("total_cash")) or 0, _num(f.get("total_debt")) or 0
        gross_m = _num(f.get("gross_margin")) or 0
        evs = _clamp(25 * rev_g, 2, 15) * (1.2 if gross_m > 0.6 else 1.0) * bump
        mid = (evs * revenue + cash - debt) / shares
        if mid <= 0:
            return None
        return {"method": f"Fair EV/sales of {evs:.1f}x", "low": round(mid * 0.8, 2),
                "mid": round(mid, 2), "high": round(mid * 1.2, 2), "stage": "early"}
    return None


def verdict(ticker: str, f: dict, m: dict | None, premium: bool) -> dict:
    """f: fundamentals, m: market status (price, sma50, sma200, trend). Returns a verdict card."""
    out = {"ticker": ticker, "verdict": "Not enough data", "tone": "", "reasons": []}
    f = {**(f or {}), "price": (m or {}).get("price")}
    if len(f) <= 1 or not m or not m.get("price"):
        out["reasons"].append("Missing price or fundamental data.")
        return out

    price, s50, s200 = m["price"], m.get("sma50"), m.get("sma200")
    q = quality(f)
    fv = fair_value(f, premium)
    out.update({"price": price, "quality": q, "fair": fv})

    if q["known"] < 3 or fv is None:
        out["reasons"].append("Not enough fundamental data to judge value.")
        return out

    early = fv["stage"] == "early"
    rev_g, gross_m = _num(f.get("revenue_growth")) or 0, _num(f.get("gross_margin")) or 0
    quality_ok = (rev_g > 0.25 and gross_m > 0.40) if early else q["passed"] >= QUALITY_MIN_PROFITABLE

    # Buy zone: fair value range clipped by chart support.
    zone_high = fv["high"] if not s50 else min(fv["high"], s50 * 1.03)
    zone_low = fv["low"] if not s200 else max(fv["low"], s200 * 0.97)
    if zone_low > zone_high:
        if s50 and s200 and fv["low"] > s50:
            # Fair value sits above the chart: the stock is cheap, so the chart's support band is the zone.
            zone_low, zone_high = min(s200, s50) * 0.97, max(s50, s200) * 1.03
        else:
            # Chart sits above fair value: value decides.
            zone_low, zone_high = fv["low"], fv["high"]
    out["zone"] = {"low": round(zone_low, 2), "high": round(zone_high, 2)}
    out["put_strike_idea"] = round(zone_low, 0) if zone_low >= 20 else round(zone_low, 1)
    floor = (s200 or zone_low) * 0.9
    out["thesis_broken_if"] = (f"Price closes below about {floor:.2f}, or revenue growth turns negative"
                               + (" or cash runs low" if early else "") + ".")

    falling = m.get("trend") == "downtrend"
    extended = s50 is not None and price > s50 * 1.08

    if price < 5:
        out.update(verdict="Wait", tone="warn")
        out["reasons"].append("Under $5 a share: thinly followed and free data is less reliable. Check filings first.")
    elif not quality_ok:
        out.update(verdict="Avoid", tone="down")
        out["reasons"].append(
            "Early stage without the fast growth and margins that would justify it." if early
            else f"Passes only {q['passed']} of {q['known']} quality checks.")
    elif price > fv["high"] * 1.25:
        out.update(verdict="Wait", tone="warn")
        out["reasons"].append(f"Price is {100 * (price / fv['high'] - 1):.0f}% above the top of fair value.")
    elif falling:
        out.update(verdict="Wait", tone="warn")
        out["reasons"].append("Good business, but the chart is in a downtrend. Wait for a base to form.")
    elif zone_low <= price <= zone_high * 1.02 and not extended:
        out.update(verdict="Buy zone now", tone="up")
        out["reasons"].append("Quality business below fair value, sitting near support." if price < fv["low"]
                              else "Quality business, fair price, sitting near support.")
    else:
        out.update(verdict="Accumulate on pullback", tone="accent")
        out["reasons"].append("Good business but the price is stretched. Wait for the buy zone.")
    if early:
        out["reasons"].append("Early stage company: valued on sales, so expect bigger swings.")
    return out
