"""Free daily data from Yahoo Finance via yfinance, with a same-day disk cache."""

import pickle
from datetime import date, datetime
from pathlib import Path

import pandas as pd

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"


def _cache_path(name: str) -> Path:
    CACHE_DIR.mkdir(exist_ok=True)
    return CACHE_DIR / f"{date.today().isoformat()}-{name}.pkl"


def load_prices(tickers: list[str], period: str = "2y", chunk: int = 100) -> dict[str, pd.DataFrame]:
    """Daily OHLCV per ticker. Tickers that fail to download are skipped."""
    import yfinance as yf

    path = _cache_path("prices")
    if path.exists():
        cached = pickle.loads(path.read_bytes())
        if set(tickers) <= set(cached):
            return {t: cached[t] for t in tickers}

    out: dict[str, pd.DataFrame] = {}
    for i in range(0, len(tickers), chunk):
        batch = tickers[i : i + chunk]
        raw = yf.download(
            batch, period=period, interval="1d", group_by="ticker",
            auto_adjust=True, threads=True, progress=False,
        )
        for t in batch:
            try:
                df = raw[t] if isinstance(raw.columns, pd.MultiIndex) else raw
                df = df.dropna(subset=["Close"])
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
