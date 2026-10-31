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


def up_down_volume(df: pd.DataFrame, n: int = 50) -> float:
    """Volume on up days divided by volume on down days over the last n days.
    Above 1 means buyers are doing the heavy lifting (accumulation); below 1 means distribution."""
    chg = df["Close"].diff().tail(n)
    vol = df["Volume"].tail(n)
    up, down = float(vol[chg > 0].sum()), float(vol[chg < 0].sum())
    return round(up / down, 2) if down > 0 else (9.99 if up > 0 else np.nan)


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
        "vol1": float(vol.iloc[-1]),
        "up_down_vol": up_down_volume(df),
        "atr14": float(atr(df).iloc[-1]),
        "ret63": pct_change(close, 63),
        "ret21": pct_change(close, 21),
        "ret126": pct_change(close, 126),
        "hv20": realized_vol(close, 20),
    }
    snap["spy_ret63"] = pct_change(spy["Close"], 63) if spy is not None else np.nan
    return snap


def swing_structure(df: pd.DataFrame, k: int = 10, lookback: int = 252) -> dict | None:
    """Lower highs and lower lows, read the way a trader reads a chart.

    A swing high is a High above the k bars on each side (10 keeps the small wiggles out; with 5, PWR's
    Sep 2026 bounce counted as a swing high and hid its lower highs). Take the last two swing highs. The trend is falling
    when the last swing high is under the one before it, the lowest low since the last swing high is under the
    lowest low between the two highs, and the price has not broken back over the last swing high.
    None when there are not two swing highs to compare."""
    d = df.tail(lookback)
    high, low = d["High"].to_numpy(), d["Low"].to_numpy()
    piv = [i for i in range(k, len(d) - k) if high[i] == high[i - k:i + k + 1].max() and high[i] > high[i - k:i].max()]
    if len(piv) < 2:
        return None
    h1, h2 = piv[-2], piv[-1]
    low_between, low_since = float(low[h1:h2 + 1].min()), float(low[h2 + 1:].min()) if h2 + 1 < len(d) else None
    if low_since is None:
        return None
    price = float(d["Close"].iloc[-1])
    falling = bool(high[h2] < high[h1] and low_since < low_between and price < high[h2])
    return {"lower_highs_lows": falling, "high_prev": round(float(high[h1]), 2), "high_last": round(float(high[h2]), 2),
            "low_prev": round(low_between, 2), "low_last": round(low_since, 2)}
