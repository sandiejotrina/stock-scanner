from stockscan.legends import compare, parse_info_table, signals

XML = """<?xml version="1.0"?>
<informationTable xmlns="http://www.sec.gov/edgar/document/thirteenf/informationtable">
  <infoTable><nameOfIssuer>APPLE INC</nameOfIssuer><cusip>037833100</cusip><value>600</value>
    <shrsOrPrnAmt><sshPrnamt>300</sshPrnamt><sshPrnamtType>SH</sshPrnamtType></shrsOrPrnAmt></infoTable>
  <infoTable><nameOfIssuer>ALPHABET INC</nameOfIssuer><cusip>02079K305</cusip><value>300</value>
    <shrsOrPrnAmt><sshPrnamt>100</sshPrnamt></shrsOrPrnAmt></infoTable>
  <infoTable><nameOfIssuer>ALPHABET INC</nameOfIssuer><cusip>02079K305</cusip><value>100</value>
    <shrsOrPrnAmt><sshPrnamt>50</sshPrnamt></shrsOrPrnAmt></infoTable>
  <infoTable><nameOfIssuer>SPDR S&amp;P 500</nameOfIssuer><cusip>78462F103</cusip><value>999</value>
    <shrsOrPrnAmt><sshPrnamt>10</sshPrnamt></shrsOrPrnAmt><putCall>Put</putCall></infoTable>
</informationTable>"""


def test_parse_merges_rows_and_skips_options():
    t = parse_info_table(XML)
    assert set(t) == {"037833100", "02079K305"}
    assert t["02079K305"]["shares"] == 150 and t["02079K305"]["value"] == 400
    assert t["037833100"]["name"] == "Apple Inc"


def test_compare_finds_new_adds_cuts_and_exits():
    prev = {"037833100": {"name": "Apple", "value": 900, "shares": 450},   # cut
            "02079K305": {"name": "Alphabet", "value": 100, "shares": 50},  # add
            "21036P108": {"name": "Constellation", "value": 50, "shares": 5}}  # exit
    cur = parse_info_table(XML)
    cur["25754A201"] = {"name": "Dr Horton", "value": 10, "shares": 1}  # new
    top, bought, sold = compare(cur, prev)
    assert top[0]["cusip"] == "037833100" and round(sum(r["pct"] for r in top)) == 100
    assert {(r["cusip"], r["action"]) for r in bought} == {("02079K305", "add"), ("25754A201", "new")}
    assert {(r["cusip"], r["action"]) for r in sold} == {("037833100", "cut"), ("21036P108", "exit")}


def test_signals_group_buyers_and_sellers_by_ticker():
    lg = [{"name": "Buffett", "bought": [{"ticker": "GOOGL"}], "sold": [{"ticker": "BAC"}]},
          {"name": "Druckenmiller", "bought": [{"ticker": "googl"}], "sold": []}]
    s = signals(lg)
    assert s["GOOGL"]["buyers"] == ["Buffett", "Druckenmiller"] and s["BAC"]["sellers"] == ["Buffett"]


def test_signals_skip_stale_filings():
    lg = [{"name": "A", "quarter": "2026-06-30", "bought": [{"ticker": "X"}], "sold": []},
          {"name": "B", "quarter": "2025-09-30", "bought": [{"ticker": "X"}], "sold": [{"ticker": "PLTR"}]}]
    s = signals(lg)
    assert s["X"]["buyers"] == ["A"] and "PLTR" not in s
