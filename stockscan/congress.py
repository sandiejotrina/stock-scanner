"""Stock trades disclosed by members of Congress (STOCK Act periodic transaction reports).

Read this before trusting it:
- Members can file up to 45 days after the trade, so this is old news by design.
- Studies find no reliable edge from copying Congress as a whole (Eggers and Hainmueller 2013,
  Belmont et al. 2022). The exception is party leadership, whose trades beat their peers
  (Wei and Zhou 2025, NBER w34524). So leaders are weighted up and everyone else is a
  confirming signal, not a reason to buy.

Sources, tried in order:
1. Quiver Quantitative live feed: both chambers, already structured. Free access is not guaranteed.
2. House Clerk: official, free, House only. E-filed PDFs are parsed with pdfplumber.
"""

import io
import re
import zipfile
from datetime import date, datetime, timedelta

import requests

HEADERS = {"User-Agent": "Mozilla/5.0 (stock-scanner research)"}

# Party leadership in the 119th Congress. Update when leadership changes.
LEADERS = {
    "johnson": "Speaker of the House", "scalise": "House Majority Leader", "emmer": "House Majority Whip",
    "jeffries": "House Minority Leader", "clark": "House Minority Whip", "aguilar": "House Dem Caucus Chair",
    "thune": "Senate Majority Leader", "barrasso": "Senate Majority Whip",
    "schumer": "Senate Minority Leader", "durbin": "Senate Minority Whip",
}

AMOUNT_LOW = {
    "$1,001": 1001, "$15,001": 15001, "$50,001": 50001, "$100,001": 100001, "$250,001": 250001,
    "$500,001": 500001, "$1,000,001": 1000001, "$5,000,001": 5000001, "$25,000,001": 25000001,
}


def amount_low(text: str) -> int:
    m = re.search(r"\$[\d,]+", text or "")
    if not m:
        return 0
    return AMOUNT_LOW.get(m.group(0), int(re.sub(r"[^\d]", "", m.group(0)) or 0))


def leader_role(name: str) -> str | None:
    """Match on last name, which is how the feeds spell people consistently."""
    last = (name or "").replace(",", " ").split()
    for word in last:
        role = LEADERS.get(word.lower())
        if role:
            # Common last names ("Johnson", "Clark") belong to several members, so require the chamber
            # level first name too when we know it.
            if word.lower() == "johnson" and "mike" not in name.lower():
                return None
            if word.lower() == "clark" and "katherine" not in name.lower():
                return None
            return role
    return None


def _date(text) -> str | None:
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return datetime.strptime(str(text)[: len(fmt) + 6].strip(), fmt).date().isoformat()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(str(text).replace("Z", "")).date().isoformat()
    except ValueError:
        return None


def _lag(traded: str | None, filed: str | None) -> int | None:
    if not traded or not filed:
        return None
    return (date.fromisoformat(filed) - date.fromisoformat(traded)).days


def _row(source, person, chamber, party, ticker, tx, traded, filed, amount, owner="", url=""):
    tx_l = (tx or "").lower()
    kind = "buy" if tx_l.startswith(("p", "buy")) else "sell" if tx_l.startswith(("s", "sale", "sell")) else "other"
    return {
        "source": source, "person": person, "chamber": chamber, "party": party,
        "ticker": (ticker or "").upper().strip(), "type": kind, "traded": traded, "filed": filed,
        "lag_days": _lag(traded, filed), "amount": amount, "amount_low": amount_low(amount),
        "owner": owner, "leader": leader_role(person), "url": url,
    }


# ---------- Source 1: Quiver ----------

def fetch_quiver(days: int) -> list[dict]:
    resp = requests.get("https://api.quiverquant.com/beta/live/congresstrading", headers=HEADERS, timeout=60)
    resp.raise_for_status()
    rows = resp.json()
    if not isinstance(rows, list):
        raise ValueError("Quiver returned no list")
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    out = []
    for r in rows:
        filed = _date(r.get("ReportDate"))
        if not filed or filed < cutoff or not r.get("Ticker"):
            continue
        party = r.get("Party") or ""
        out.append(_row(
            "Quiver", r.get("Representative", ""), r.get("House", ""), party[:1],
            r.get("Ticker"), r.get("Transaction", ""), _date(r.get("TransactionDate")), filed,
            r.get("Range") or str(r.get("Amount", "")),
        ))
    return out


# ---------- Source 2: House Clerk ----------

CLERK = "https://disclosures-clerk.house.gov/public_disc"
LINE = re.compile(
    r"^(?:(?P<owner>SP|JT|DC)\s+)?(?P<asset>.+?\((?P<ticker>[A-Z.\-]{1,6})\)\s*\[(?P<kind>[A-Z]{2})\])\s*"
    r"(?P<tx>P|S \(partial\)|S|E)\s+(?P<traded>\d{2}/\d{2}/\d{4})\s+(?P<notified>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<amount>\$[\d,]+(?:\s*-\s*\$[\d,]+)?)",
    re.M,
)


def house_filings(year: int, days: int) -> list[dict]:
    resp = requests.get(f"{CLERK}/financial-pdfs/{year}FD.zip", headers=HEADERS, timeout=120)
    resp.raise_for_status()
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    txt = zf.read(f"{year}FD.txt").decode("utf-8", errors="ignore").splitlines()
    head = txt[0].split("\t")
    cutoff = date.today() - timedelta(days=days)
    out = []
    for line in txt[1:]:
        f = dict(zip(head, line.split("\t")))
        if f.get("FilingType") != "P":
            continue
        filed = _date(f.get("FilingDate"))
        if filed and date.fromisoformat(filed) >= cutoff:
            out.append({**f, "filed": filed})
    return out


def parse_house_ptr(text: str, filing: dict) -> list[dict]:
    person = f"{filing.get('First', '')} {filing.get('Last', '')}".strip()
    url = f"{CLERK}/ptr-pdfs/{filing.get('Year')}/{filing.get('DocID')}.pdf"
    rows = []
    for m in LINE.finditer(text):
        if m.group("kind") != "ST":
            continue
        rows.append(_row(
            "House Clerk", person, "House", "", m.group("ticker"), m.group("tx"),
            _date(m.group("traded")), filing["filed"], m.group("amount"), m.group("owner") or "",
            url,
        ))
    return rows


def fetch_house(days: int, max_filings: int = 200) -> list[dict]:
    import pdfplumber

    year = date.today().year
    filings = house_filings(year, days)
    if date.today().timetuple().tm_yday <= days:
        filings += house_filings(year - 1, days)
    out = []
    for f in filings[:max_filings]:
        if str(f.get("DocID", "")).startswith("8"):
            continue  # scanned paper filing: no text to parse
        try:
            pdf = requests.get(f"{CLERK}/ptr-pdfs/{f['Year']}/{f['DocID']}.pdf", headers=HEADERS, timeout=60)
            pdf.raise_for_status()
            with pdfplumber.open(io.BytesIO(pdf.content)) as doc:
                text = "\n".join(page.extract_text() or "" for page in doc.pages)
            out.extend(parse_house_ptr(text, f))
        except Exception:
            continue
    return out


# ---------- Combine ----------

def summarize(rows: list[dict]) -> list[dict]:
    """Per ticker: who bought, who sold, and whether any leader is involved."""
    by = {}
    for r in rows:
        if not r["ticker"] or r["type"] == "other":
            continue
        t = by.setdefault(r["ticker"], {"ticker": r["ticker"], "buyers": set(), "sellers": set(),
                                        "leaders": set(), "buy_low": 0, "last_filed": ""})
        (t["buyers"] if r["type"] == "buy" else t["sellers"]).add(r["person"])
        if r["type"] == "buy":
            t["buy_low"] += r["amount_low"]
            if r["leader"]:
                t["leaders"].add(f"{r['person']} ({r['leader']})")
        t["last_filed"] = max(t["last_filed"], r["filed"] or "")
    out = []
    for t in by.values():
        out.append({
            "ticker": t["ticker"], "buyers": sorted(t["buyers"]), "sellers": sorted(t["sellers"]),
            "leaders": sorted(t["leaders"]), "net_buyers": len(t["buyers"]) - len(t["sellers"]),
            "buy_amount_min": t["buy_low"], "last_filed": t["last_filed"],
        })
    return sorted(out, key=lambda r: (len(r["leaders"]), r["net_buyers"], r["buy_amount_min"]), reverse=True)


def fetch(days: int = 60) -> dict:
    """Try each source. Record what worked so the dashboard can say so."""
    rows, used, errors = [], [], []
    try:
        rows = fetch_quiver(days)
        used.append("Quiver")
    except Exception as e:
        errors.append(f"Quiver: {e}")
    if not rows:
        try:
            rows = fetch_house(days)
            used.append("House Clerk (House only)")
        except Exception as e:
            errors.append(f"House Clerk: {e}")
    rows.sort(key=lambda r: r["filed"] or "", reverse=True)
    return {"sources": used, "errors": errors, "trades": rows, "by_ticker": summarize(rows)}
