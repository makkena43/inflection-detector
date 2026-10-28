"""Insider-trade and bulk/block-deal rows from NSE's APIs."""
from datetime import date
from decimal import Decimal

from inflection.deals import parse_deal, parse_pit

PIT = {"acqMode": "Market Purchase", "acqName": "Jindal Power Limited", "acqfromDt": "29-Aug-2025", "acqtoDt": "29-Aug-2025",
       "afterAcqSharesPer": "1.18", "company": "JINDAL STEEL LIMITED", "date": "03-Sep-2025 23:49", "did": "550187",
       "personCategory": "Promoter Group", "pid": "1187100", "secAcq": "88124", "secVal": "83384584", "symbol": "JINDALSTEL",
       "tdpTransactionType": "Buy"}
DEAL = {"BD_DT_DATE": "01-SEP-2026", "BD_SYMBOL": "HATSUN", "BD_SCRIP_NAME": "Hatsun Agro Product Ltd.", "BD_CLIENT_NAME": "CHANDRAMOGAN R G",
        "BD_BUY_SELL": "buy", "BD_QTY_TRD": 825000, "BD_TP_WATP": 1192, "BD_REMARKS": None}


def test_pit_row():
    r = parse_pit(PIT)
    assert r[:7] == ("NSE", "JINDALSTEL", "JINDAL STEEL LIMITED", "Jindal Power Limited", "Promoter Group", "Buy", "Market Purchase")
    assert r[8] == Decimal("83384584") and r[9] == r[10] == date(2025, 8, 29) and r[11].hour == 23 and r[12] == Decimal("1.18")
    assert parse_pit(PIT)[-1] == r[-1] and parse_pit({**PIT, "secAcq": "1"})[-1] != r[-1]     # stable, distinct refs
    assert parse_pit({**PIT, "symbol": ""}) is None


def test_deal_row():
    r = parse_deal(DEAL, "BLOCK")
    assert r[:4] == ("NSE", "BLOCK", date(2026, 9, 1), "HATSUN") and r[6] == "BUY" and r[7] == Decimal("825000")
    assert r[-1].startswith("nse_block:") and parse_deal(DEAL, "BLOCK")[-1] == r[-1]
    assert parse_deal({**DEAL, "BD_DT_DATE": "bad"}, "BULK") is None
