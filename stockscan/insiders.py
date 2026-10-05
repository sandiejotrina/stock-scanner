"""Corporate insider open market purchases (SEC Form 4, code P) via OpenInsider.

Only purchases count here. Insiders sell for many reasons (taxes, houses, diversifying)
but buy with their own cash for one reason: they think the stock is going up.
"""

import io
import re

import pandas as pd
import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (stock-scanner research)"}

SCREENER = (
    "http://openinsider.com/screener?s=&o=&pl=&ph=&ll=&lh=&fd={days}&fdr=&td=0&tdr=&fdlyl=&fdlyh="
    "&daysago=&xp=1&vl={min_k}&vh=&ocl=&och=&sic1=-1&sicl=100&sich=9999&grp=0&nfl=&nfh=&nil=&nih="
    "&nol=&noh=&v2l=&v2h=&oc2l=&oc2h=&sortcol=0&cnt=1000&page=1"
)

ROLE_WEIGHT = {"CEO": 3, "CFO": 2, "COB": 2, "Pres": 2, "COO": 2, "Dir": 1, "10%": 1}


def _clean_cols(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [re.sub(r"\s+", " ", str(c).replace("\xa0", " ")).strip() for c in df.columns]
    return df


def _money(x) -> float:
    s = re.sub(r"[^0-9.\-]", "", str(x))
    return float(s) if s not in ("", "-", ".") else 0.0


def parse_openinsider(html: str) -> pd.DataFrame:
    """Turn the OpenInsider screener table into tidy rows."""
    tables = pd.read_html(io.StringIO(html))
    table = next((t for t in map(_clean_cols, tables) if {"Ticker", "Trade Type"} <= set(t.columns)), None)
    if table is None:
        return pd.DataFrame()
    df = table[table["Trade Type"].astype(str).str.startswith("P")].copy()
    return pd.DataFrame({
        "filed": pd.to_datetime(df["Filing Date"], errors="coerce").dt.strftime("%Y-%m-%d"),
        "traded": pd.to_datetime(df["Trade Date"], errors="coerce").dt.strftime("%Y-%m-%d"),
        "ticker": df["Ticker"].astype(str).str.strip().str.upper(),
        "company": df.get("Company Name", pd.Series("", index=df.index)).astype(str),
        "insider": df["Insider Name"].astype(str),
        "title": df["Title"].astype(str),
        "price": df["Price"].map(_money),
        "value": df["Value"].map(_money),
        "own_change": df.get("ΔOwn", pd.Series("", index=df.index)).astype(str),
    })


def role_weight(title: str) -> int:
    return max((w for k, w in ROLE_WEIGHT.items() if k in title), default=1)


def summarize(rows: pd.DataFrame) -> list[dict]:
    """One line per company: how many insiders bought, how much, and who."""
    if rows.empty:
        return []
    out = []
    for ticker, g in rows.groupby("ticker"):
        insiders = g["insider"].nunique()
        total = float(g["value"].sum())
        weight = int(g["title"].map(role_weight).max())
        out.append({
            "ticker": ticker,
            "company": g["company"].iloc[0],
            "insiders": int(insiders),
            "cluster": bool(insiders >= 2),
            "total_value": round(total),
            "top_role": g.loc[g["title"].map(role_weight).idxmax(), "title"],
            "last_trade": g["traded"].max(),
            "last_filed": g["filed"].max(),
            "avg_price": round(float((g["price"] * g["value"]).sum() / total), 2) if total else None,
            # Bigger, more senior, more people buying = stronger signal.
            "score": round(min(insiders, 5) * 2 + weight + min(total / 1e6, 5), 1),
            "trades": g.sort_values("traded", ascending=False)[
                ["traded", "insider", "title", "price", "value", "own_change"]
            ].to_dict("records"),
        })
    return sorted(out, key=lambda r: r["score"], reverse=True)


def fetch(days: int = 30, min_value_k: int = 50) -> list[dict]:
    resp = requests.get(SCREENER.format(days=days, min_k=min_value_k), headers=HEADERS, timeout=60)
    resp.raise_for_status()
    return summarize(parse_openinsider(resp.text))
