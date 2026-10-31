"""Free daily data from Yahoo Finance via yfinance, with a same-day disk cache."""

import pickle
from datetime import date, datetime, time, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"{date.today().isoformat()}-{name}.pkl"


def exchange_of(ticker: str) -> str:
    """The Yahoo exchange suffix ("T", "TW", "SW") or "US". BRK-B style class shares are US."""
    head, dot, tail = ticker.rpartition(".")
    return tail if dot and head and tail.isalpha() and len(tail) >= 1 and "-" not in ticker else "US"


def exchange_batches(tickers: list[str], chunk: int) -> list[list[str]]:
    """Download batches that never mix exchanges. A batch that mixes US names with Asian listings can come back
    without the latest US close when it runs after Asia has opened (the evening refresh), because the bars are
    lined up on one shared calendar."""
    groups: dict[str, list[str]] = {}
    for t in tickers:
        groups.setdefault(exchange_of(t), []).append(t)
    return [g[i : i + chunk] for _, g in sorted(groups.items()) for i in range(0, len(g), chunk)]


# Local time each market's daily bar is final (the close plus a margin for the closing auction and late prints).
SESSION_DONE = {
    "US": ("America/New_York", time(16, 30)),
    "T": ("Asia/Tokyo", time(15, 45)), "TW": ("Asia/Taipei", time(14, 0)), "TWO": ("Asia/Taipei", time(14, 0)),
    "KS": ("Asia/Seoul", time(16, 0)), "KQ": ("Asia/Seoul", time(16, 0)), "HK": ("Asia/Hong_Kong", time(16, 30)),
    "SS": ("Asia/Shanghai", time(15, 30)), "SZ": ("Asia/Shanghai", time(15, 30)), "NS": ("Asia/Kolkata", time(16, 0)),
    "BO": ("Asia/Kolkata", time(16, 0)), "SA": ("America/Sao_Paulo", time(17, 30)),
    "MX": ("America/Mexico_City", time(15, 30)), "BA": ("America/Argentina/Buenos_Aires", time(17, 30)),
    "L": ("Europe/London", time(17, 0)), "SR": ("Asia/Riyadh", time(15, 30)),
}
EUROPE = ("Europe/Berlin", time(18, 0))  # DE, PA, AS, MI, SW, MC, ST, CO and other European listings


def drop_unfinished_bar(df: pd.DataFrame, ticker: str, now: datetime | None = None) -> pd.DataFrame:
    """Drop today's bar while that market is still trading. A midday run otherwise treats a half day's price
    and volume as a close, and verdicts, setups and volume checks are built on it (seen 2026-10-30)."""
    if df is None or len(df) == 0:
        return df
    now = now or datetime.now(timezone.utc)
    ex = exchange_of(ticker) if not ticker.startswith("^") else "US"
    tz, done = SESSION_DONE.get(ex, EUROPE if ex != "US" else SESSION_DONE["US"])
    local = now.astimezone(ZoneInfo(tz))
    last = df.index[-1]
    last_day = last.date() if hasattr(last, "date") else last
    if last_day == local.date() and local.time() < done:
        return df.iloc[:-1]
    return df


def load_prices(tickers: list[str], period: str = "2y", chunk: int = 100) -> dict[str, pd.DataFrame]:
    """Daily OHLCV per ticker. Tickers that fail to download are skipped."""
    import yfinance as yf

    path = _cache_path("prices")
    if path.exists():
        cached = pickle.loads(path.read_bytes())
        if set(tickers) <= set(cached):
            return {t: drop_unfinished_bar(cached[t], t) for t in tickers}

    out: dict[str, pd.DataFrame] = {}
    for batch in exchange_batches(tickers, chunk):
        raw = yf.download(
            batch, period=period, interval="1d", group_by="ticker",
            auto_adjust=True, threads=True, progress=False,
        )
        for t in batch:
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = drop_unfinished_bar(df.dropna(subset=["Close"]), t)
                if len(df) >= 210:
                    out[t] = df
            except KeyError:
                continue
    path.write_bytes(pickle.dumps(out))
    return out


def _to_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (ValueError, TypeError):
        return None


def company_events(ticker: str) -> dict:
    """Next earnings date, ex-dividend date and market cap. Missing values come back as None."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    events = {"earnings": None, "ex_dividend": None, "market_cap": None}
    try:
        cal = t.calendar or {}
        events["earnings"] = _to_date(cal.get("Earnings Date"))
        events["ex_dividend"] = _to_date(cal.get("Ex-Dividend Date"))
    except Exception:
        pass
    try:
        events["market_cap"] = t.fast_info.get("marketCap")
    except Exception:
        pass
    return events


def option_chain(ticker: str, min_dte: int, max_dte: int, today: date):
    """Puts and calls for the expiration closest to the middle of the DTE window."""
    import yfinance as yf

    t = yf.Ticker(ticker)
    try:
        expirations = t.options
    except Exception:
        return None
    target = (min_dte + max_dte) / 2
    best = None
    for exp in expirations:
        dte = (date.fromisoformat(exp) - today).days
        if min_dte <= dte <= max_dte and (best is None or abs(dte - target) < abs(best[1] - target)):
            best = (exp, dte)
    if best is None:
        return None
    chain = t.option_chain(best[0])
    return {"expiration": best[0], "dte": best[1], "puts": chain.puts, "calls": chain.calls}


def fundamentals(ticker: str) -> dict:
    """The handful of numbers that matter for a long term hold."""
    import yfinance as yf

    try:
        info = yf.Ticker(ticker).info
    except Exception:
        return {}
    pick = {
        "name": "shortName",
        "market_cap": "marketCap",
        "revenue_growth": "revenueGrowth",
        "earnings_growth": "earningsGrowth",
        "gross_margin": "grossMargins",
        "operating_margin": "operatingMargins",
        "fcf": "freeCashflow",
        "debt_to_equity": "debtToEquity",
        "forward_pe": "forwardPE",
        "peg": "trailingPegRatio",
    }
    return {k: info.get(v) for k, v in pick.items()}


VALUATION_FIELDS = {
    "name": "shortName", "market_cap": "marketCap", "revenue": "totalRevenue", "revenue_growth": "revenueGrowth",
    "earnings_growth": "earningsGrowth", "gross_margin": "grossMargins", "operating_margin": "operatingMargins",
    "fcf": "freeCashflow", "total_debt": "totalDebt", "total_cash": "totalCash", "ebitda": "ebitda",
    "debt_to_equity": "debtToEquity", "forward_eps": "forwardEps", "forward_pe": "forwardPE",
    "shares": "sharesOutstanding", "peg": "trailingPegRatio",
    "financial_currency": "financialCurrency", "currency": "currency",
}


def valuation_inputs(ticker: str) -> dict:
    """Everything the verdict engine needs from one Yahoo quote summary call."""
    import yfinance as yf

    try:
        info = yf.Ticker(ticker).info or {}
    except Exception:
        return {}
    out = {k: info.get(v) for k, v in VALUATION_FIELDS.items()}
    return out if any(v is not None for k, v in out.items() if k != "name") else {}
