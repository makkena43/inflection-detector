"""Order walk of the limit-order short-term book (ops/limit_book.py): fills, sell limit, stop and expiry from prices alone."""
import sys
from pathlib import Path

import numpy as np
import pytest

pytest.importorskip("psycopg")
sys.path.insert(0, str(Path(__file__).parent.parent / "ops"))
import limit_book as LB  # noqa: E402

NEVER = lambda k: False


def series(rows):
    """rows of (open, high, low, close); the 5-day average is set far above so that only the tested exit can fire."""
    a = np.array(rows, float)
    return a[:, 0], a[:, 1], a[:, 2], a[:, 3], np.full(len(a), 1e9)


def walk(rows, last=None, s5=None, limit=96.0, atr=2.0):
    O, H, L, C, S5 = series(rows)
    return LB.walk_dip(O, H, L, C, S5 if s5 is None else np.array(s5, float), NEVER, 0, len(rows) - 1 if last is None else last, limit, atr)


def test_fills_at_limit_only_when_traded_through():
    assert walk([(100, 101, 99, 100), (99, 100, 96.0, 98), (98, 99, 97, 98)])["status"] == "EXPIRED"      # touched, not through
    r = walk([(100, 101, 99, 100), (99, 100, 95.5, 97)])
    assert r["e"] == 1 and r["entry"] == 96.0


def test_gap_down_fills_at_the_open():
    r = walk([(100, 101, 99, 100), (94, 95, 93, 94.5)])
    assert r["entry"] == 94.0


def test_second_day_fill_and_pending_before_it():
    rows = [(100, 101, 99, 100), (99, 100, 97, 98), (97, 98, 95, 96)]
    assert walk(rows)["e"] == 2
    assert walk(rows, last=1) == dict(status="PENDING", days_left=1)
    assert walk(rows, last=0) == dict(status="PENDING", days_left=2)


def test_sell_limit_not_on_buy_day_then_at_limit_or_open():
    r = walk([(100, 101, 99, 100), (99, 102, 95, 101), (100, 100.5, 99, 100), (100, 101.5, 99.5, 101)])
    assert r["x"] == 3 and r["exit"] == pytest.approx(96 * 1.05) and r["reason"] == "Sell limit filled"
    r = walk([(100, 101, 99, 100), (99, 100, 95, 97), (103, 104, 102, 103)])
    assert r["x"] == 2 and r["exit"] == 103.0


def test_stop_comes_before_the_sell_limit():
    r = walk([(100, 101, 99, 100), (99, 100, 95, 97), (97, 102, 89, 95)])
    assert r["reason"] == "Stop hit" and r["exit"] == 90.0


def test_close_above_average_sells_next_open_and_time_limit():
    rows = [(100, 101, 99, 100), (99, 100, 95, 97), (97, 98, 96, 97.5), (98, 99, 97, 98)]
    r = walk(rows, s5=[1e9, 1e9, 97.0, 1e9])
    assert r["x"] == 3 and r["exit"] == 98.0
    assert walk(rows[:3], s5=[1e9, 1e9, 97.0])["due"] == "SELL NEXT OPEN"
    flat = [(100, 101, 99, 100), (99, 100, 95, 97)] + [(97, 98, 96, 97)] * 5
    r = walk(flat)
    assert r["x"] == 6 and r["reason"] == "5-day limit"
    assert walk(flat[:6])["due"] == "SELL AT CLOSE"
