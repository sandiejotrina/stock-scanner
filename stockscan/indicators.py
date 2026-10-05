"""Technical indicators computed on daily OHLCV frames.

Every function takes a DataFrame with Open, High, Low, Close, Volume columns
indexed by date, oldest first.
"""

import numpy as np
import pandas as pd


def sma(series: pd.Series, n: int) -> pd.Series:
    return series.rolling(n).mean()


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev_close = df["Close"].shift(1)
    tr = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    return tr.rolling(n).mean()


def bollinger_width(close: pd.Series, n: int = 20) -> pd.Series:
    mid = close.rolling(n).mean()
    return 4 * close.rolling(n).std() / mid


def pct_change(close: pd.Series, n: int) -> float:
    if len(close) <= n:
        return np.nan
    return close.iloc[-1] / close.iloc[-1 - n] - 1


def realized_vol(close: pd.Series, n: int = 20) -> float:
    """Annualized close to close volatility over the last n days."""
    rets = np.log(close / close.shift(1)).dropna().tail(n)
    return float(rets.std() * np.sqrt(252))


def snapshot(df: pd.DataFrame, spy: pd.DataFrame | None = None) -> dict:
    """Latest values of everything the scans need, as plain floats."""
    close = df["Close"]
    s50 = sma(close, 50)
    s200 = sma(close, 200)
    bbw = bollinger_width(close)
    vol = df["Volume"]
    base = df.tail(25)

    snap = {
        "price": float(close.iloc[-1]),
        "sma50": float(s50.iloc[-1]),
        "sma200": float(s200.iloc[-1]),
        "sma50_20ago": float(s50.iloc[-21]) if len(s50) > 21 else np.nan,
        "sma200_20ago": float(s200.iloc[-21]) if len(s200) > 21 else np.nan,
        "high50": float(df["High"].tail(50).max()),
        "low20": float(df["Low"].tail(20).min()),
        "base_low": float(base["Low"].min()),
        "base_depth": float((base["High"].max() - base["Low"].min()) / base["High"].max()),
        "bbw": float(bbw.iloc[-1]),
        "bbw_avg50": float(bbw.tail(50).mean()),
        "vol10": float(vol.tail(10).mean()),
        "vol50": float(vol.tail(50).mean()),
        "atr14": float(atr(df).iloc[-1]),
        "ret63": pct_change(close, 63),
        "hv20": realized_vol(close, 20),
    }
    snap["spy_ret63"] = pct_change(spy["Close"], 63) if spy is not None else np.nan
    return snap
