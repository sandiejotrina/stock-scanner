"""Great minds: what famous investors bought and sold, from their SEC 13F filings.

The research files in research/legends/ hold the curated view (style, quotes, sources) and a hand checked
copy of the latest quarter. When the SEC is reachable, refresh() replaces the holdings with the newest
filing and works out the buys and sells against the quarter before. CUSIPs are turned into tickers with
OpenFIGI and cached, so each CUSIP is looked up once.
"""
from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET

import requests

# The SEC refuses requests without a name and a contact email. This is the repo's public GitHub noreply address.
UA = {"User-Agent": "MoneyTrail research sandiejotrina@users.noreply.github.com", "Accept-Encoding": "gzip, deflate"}
CHANGE = 0.2  # a 20% change in share count counts as an add or a cut
TOP = 10


def parse_info_table(xml: str) -> dict[str, dict]:
    """13F information table -> {cusip: {"name", "value", "shares"}} for stock rows (options left out)."""
    xml = re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", xml)
    xml = re.sub(r"<(/?)\w+:", r"<\1", xml)
    out: dict[str, dict] = {}
    for row in ET.fromstring(xml).iter("infoTable"):
        if (row.findtext("putCall") or "").strip():
            continue
        cusip = (row.findtext("cusip") or "").strip().upper()
        if not cusip:
            continue
        r = out.setdefault(cusip, {"name": (row.findtext("nameOfIssuer") or "").strip().title(), "value": 0.0, "shares": 0.0})
        r["value"] += float(row.findtext("value") or 0)
        r["shares"] += float(row.findtext("shrsOrPrnAmt/sshPrnamt") or 0)
    return out


def compare(cur: dict[str, dict], prev: dict[str, dict]) -> tuple[list, list, list]:
    """Top holdings by weight, buys (new and adds) and sells (exits and cuts), biggest first."""
    total = sum(r["value"] for r in cur.values()) or 1
    top = sorted(({"cusip": c, **r, "pct": round(100 * r["value"] / total, 1)} for c, r in cur.items()),
                 key=lambda r: -r["value"])[:TOP]
    bought, sold = [], []
    for c, r in cur.items():
        p = prev.get(c)
        if p is None:
            bought.append({"cusip": c, "name": r["name"], "action": "new", "value": r["value"]})
        elif p["shares"] and r["shares"] > p["shares"] * (1 + CHANGE):
            bought.append({"cusip": c, "name": r["name"], "action": "add", "value": r["value"] - p["value"],
                           "note": f"shares up {round(100 * (r['shares'] / p['shares'] - 1))}%"})
        elif p["shares"] and r["shares"] < p["shares"] * (1 - CHANGE):
            sold.append({"cusip": c, "name": r["name"], "action": "cut", "value": p["value"] - r["value"],
                         "note": f"shares down {round(100 * (1 - r['shares'] / p['shares']))}%"})
    for c, p in prev.items():
        if c not in cur:
            sold.append({"cusip": c, "name": p["name"], "action": "exit", "value": p["value"]})
    bought.sort(key=lambda r: -r["value"])
    sold.sort(key=lambda r: -r["value"])
    return top, bought[:8], sold[:8]


def _get(url: str, **kw):
    r = requests.get(url, headers=UA, timeout=30, **kw)
    r.raise_for_status()
    time.sleep(0.2)  # SEC asks for no more than 10 requests a second
    return r


def latest_two(cik: str) -> list[dict]:
    sub = _get(f"https://data.sec.gov/submissions/CIK{cik}.json").json()["filings"]["recent"]
    rows = [{"acc": a, "quarter": q, "filed": f} for a, form, q, f in
            zip(sub["accessionNumber"], sub["form"], sub["reportDate"], sub["filingDate"]) if form == "13F-HR"]
    seen, out = set(), []
    for r in rows:  # newest first; skip a second filing for the same quarter
        if r["quarter"] not in seen:
            seen.add(r["quarter"])
            out.append(r)
        if len(out) == 2:
            break
    return out


def holdings(cik: str, acc: str) -> dict[str, dict]:
    base = f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{acc.replace('-', '')}"
    items = _get(f"{base}/index.json").json()["directory"]["item"]
    xmls = [i["name"] for i in items if i["name"].lower().endswith(".xml") and "primary_doc" not in i["name"].lower()]
    for name in xmls:
        table = parse_info_table(_get(f"{base}/{name}").text)
        if table:
            return table
    return {}


def map_cusips(cusips: list[str], cache: dict) -> dict:
    """CUSIP -> US ticker via OpenFIGI, 10 per request, cached. Unknown ones are cached as ""."""
    todo = [c for c in dict.fromkeys(cusips) if c not in cache]
    for i in range(0, len(todo), 10):
        batch = todo[i:i + 10]
        r = requests.post("https://api.openfigi.com/v3/mapping", timeout=30,
                          json=[{"idType": "ID_CUSIP", "idValue": c, "exchCode": "US"} for c in batch])
        r.raise_for_status()
        for c, res in zip(batch, r.json()):
            data = res.get("data") or []
            cache[c] = (data[0].get("ticker") or "").replace("/", ".") if data else ""
        time.sleep(2.6)  # 25 requests a minute without an API key
    return cache


def refresh(legend: dict, cache: dict) -> dict:
    """The legend with holdings from the newest 13F. Raises on any network or parsing problem."""
    filings = latest_two(legend["cik"])
    if not filings:
        raise ValueError("no 13F-HR filings")
    cur = holdings(legend["cik"], filings[0]["acc"])
    prev = holdings(legend["cik"], filings[1]["acc"]) if len(filings) > 1 else {}
    top, bought, sold = compare(cur, prev)
    map_cusips([r["cusip"] for r in top + bought + sold], cache)

    def tick(rows):
        return [{k: v for k, v in {**r, "ticker": cache.get(r["cusip"], "")}.items() if k not in ("cusip", "value")}
                for r in rows]
    return {**legend, "quarter": filings[0]["quarter"], "filed": filings[0]["filed"], "auto": True,
            "top": tick(top), "bought": tick(bought), "sold": tick(sold)}


def signals(legends: list[dict]) -> dict[str, dict]:
    """ticker -> {"buyers": [names], "sellers": [names]} from the latest quarter. Puts listed under "sold"
    count as selling; only investors whose filing is for the newest quarter count."""
    out: dict[str, dict] = {}
    newest = max((lg.get("quarter", "") for lg in legends), default="")
    for lg in legends:
        if lg.get("quarter", "") < newest:
            continue  # an older filing (e.g. a fund that stopped filing) says nothing about now
        who = lg["name"]
        for r in lg.get("bought", []):
            if r.get("ticker"):
                out.setdefault(r["ticker"].upper(), {"buyers": [], "sellers": []})["buyers"].append(who)
        for r in lg.get("sold", []):
            if r.get("ticker"):
                out.setdefault(r["ticker"].upper(), {"buyers": [], "sellers": []})["sellers"].append(who)
    return out
