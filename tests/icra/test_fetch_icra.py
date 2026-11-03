import pytest

pytest.importorskip("pdfplumber")
pytest.importorskip("fitz")  # PyMuPDF; the ICRA scripts need it, the inflection venv does not ship it
import importlib.util
from datetime import date
from pathlib import Path

spec = importlib.util.spec_from_file_location('fetch_icra', Path(__file__).resolve().parents[2] / 'scripts/icra/fetch_icra.py')
icra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(icra)


def test_upgrade_requires_history_and_higher_grade():
    assert icra.upgrade_evidence('[ICRA]A; upgraded from [ICRA]BBB+') == []
    assert icra.upgrade_evidence('[ICRA]BBB; upgraded from [ICRA]A\nRating history\n[ICRA]BBB [ICRA]A') == []
    assert icra.upgrade_evidence('[ICRA]A (Stable); upgraded from [ICRA]BBB+\nRating history\n[ICRA]A [ICRA]BBB+')[0]['old_rating'] == 'BBB+'
    assert icra.upgrade_evidence('Outlook upgraded to Positive\nRating history\n[ICRA]A [ICRA]A') == []


def test_backtest_future_horizon_and_next_day_entry():
    events = [dict(report_id='1', date='2025-01-01', symbol='ABC')]
    prices = [dict(symbol='ABC', date=d, adjusted_close=p) for d, p in [('2025-01-01', '50'), ('2025-01-02', '100'), ('2025-04-02', '110'), ('2025-06-01', '120')]]
    rows = icra.backtest(events, prices, date(2025, 6, 1))
    assert rows[0]['return_pct'] == 10
    assert rows[0]['entry_date'] == '2025-01-02'
    assert rows[1]['status'] == 'not_matured'
    assert rows[-1]['return_pct'] == 20


def test_instrument_words_are_not_rating_symbols():
    evidence = icra.upgrade_evidence('Fund-based - Term Loan 493.00 [ICRA]AA- (Positive); upgraded from [ICRA]A (Positive)\nRating history\nTerm Loan [ICRA]AA- [ICRA]A')
    assert evidence[0]['new_rating'] == 'AA-'


def test_dual_rating_transition():
    evidence = icra.upgrade_evidence('[ICRA]AA-/[ICRA]A1+; Upgraded from [ICRA]A+/[ICRA]A1\nRating history\nBank facilities [ICRA]AA- [ICRA]A+ [ICRA]A1+ [ICRA]A1')
    assert {(e['old_rating'],e['new_rating']) for e in evidence} == {('A+','AA-'),('A1','A1+')}
