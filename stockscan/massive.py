"""Latest US closes from Massive, to fill the sessions Yahoo has not delivered yet.

Yahoo keeps the long price history (two years, dividend adjusted). It often misses the newest close on the
evening run, so the dashboard showed yesterday's prices most mornings (Oct 2026). Massive's grouped daily bars
return every US stock's open, high, low, close and volume for one session in a single call, so filling the gap
costs one call per missing session, well inside the free plan's rate limit.

Needs the MASSIVE_API_KEY environment variable (a GitHub Actions secret). Without it nothing changes.
"""
from __future__ import annotations

import os
import time
from datetime import date, timedelta

import pandas as pd
import requests

from .data import exchange_of

BASE = "https://api.massive.com"
MAX_SESSIONS = 5  # never fill more than a week; a longer gap means Yahoo is broken and needs a person


def api_key() -> str | None:
    return os.environ.get("MASSIVE_API_KEY", "").strip() or None


def massive_symbol(yahoo_symbol: str) -> str | None:
    """BRK-B on Yahoo is BRK.B on Massive. Foreign listings and indexes are not in the US grouped bars."""
    if yahoo_symbol.startswith("^") or exchange_of(yahoo_symbol) != "US":
        return None
    return yahoo_symbol.replace("-", ".")


def grouped_day(day: date, key: str, http=requests, tries: int = 4) -> pd.DataFrame | None:
    """Every US stock's bar for one session, indexed by symbol. None when the session has no data
    (a holiday, or the bars are not published yet)."""
    url = f"{BASE}/v2/aggs/grouped/locale/us/market/stocks/{day.isoformat()}"
    for attempt in range(tries):
        r = http.get(url, params={"adjusted": "true", "apiKey": key}, timeout=60)
        if r.status_code == 429 and attempt < tries - 1:
            time.sleep(15)  # free plan: 5 calls a minute
            continue
        r.raise_for_status()
        break
    rows = r.json().get("results") or []
    if not rows:
        return None
    df = pd.DataFrame(rows).set_index("T")
    return df.rename(columns={"o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume"})[
        ["Open", "High", "Low", "Close", "Volume"]]


def missing_sessions(last_bar: date, through: date) -> list[date]:
    """Weekdays after the newest bar, up to the last finished session. Holidays come back empty and are skipped."""
    out, d = [], last_bar + timedelta(days=1)
    while d <= through:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out[-MAX_SESSIONS:]


def fill_latest(prices: dict[str, pd.DataFrame], through: date, key: str, http=requests) -> tuple[dict, list[str]]:
    """Append Massive bars for the sessions each US ticker is missing, up to `through` (the last finished
    session). Returns the prices and the sessions that were filled."""
    # A delisted name with months-old data must not drag the start back, so only recent histories count.
    lasts = [d for s, df in prices.items() if massive_symbol(s) and len(df)
             and (d := df.index[-1].date()) >= through - timedelta(days=10)]
    if not lasts:
        return prices, []
    filled = []
    for day in missing_sessions(min(lasts), through):
        bars = grouped_day(day, key, http)
        if bars is None:
            continue
        stamp, hit = pd.Timestamp(day), False
        for s, df in prices.items():
            sym = massive_symbol(s)
            if not sym or sym not in bars.index or (len(df) and df.index[-1] >= stamp):
                continue
            row = bars.loc[[sym]].set_axis([stamp]).reindex(columns=df.columns)
            prices[s] = pd.concat([df, row])
            hit = True
        if hit:
            filled.append(day.isoformat())
    return prices, filled
