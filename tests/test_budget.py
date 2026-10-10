"""Budget reservations against a real PostgreSQL (skipped without INFLECTION_TEST_DSN)."""

from datetime import date
from decimal import Decimal

import pytest

from inflection.budget import BudgetExhausted, BudgetRefused, mark_unresolved, release, reserve, settle

ON = date(2026, 10, 10)
CALL = dict(on=ON, provider="anthropic", model="m1", max_input_tokens=80_000, max_output_tokens=12_000)


def setup(db, limit="10", enabled=True, price=True):
    db.execute("INSERT INTO budgets (budget_month, currency, limit_amount, paid_calls_enabled, set_by) "
               "VALUES ('2026-10-01', 'USD', %s, %s, 'investor')", (limit, enabled))
    if price:
        db.execute("INSERT INTO model_prices (provider, model, currency, input_per_mtok, output_per_mtok, "
                   "effective_from, source) VALUES ('anthropic', 'm1', 'USD', 3, 15, '2026-01-01', 'price page')")


def test_no_budget_refuses(db):
    with pytest.raises(BudgetRefused, match="no budget"):
        reserve(db, **CALL)


def test_disabled_refuses(db):
    setup(db, enabled=False)
    with pytest.raises(BudgetRefused, match="disabled"):
        reserve(db, **CALL)


def test_missing_price_fails_closed(db):
    setup(db, price=False)
    with pytest.raises(BudgetRefused, match="no USD price"):
        reserve(db, **CALL)


def test_worst_case_reserved_and_exhaustion(db):
    setup(db, limit="1.00")
    r = reserve(db, **CALL)
    assert r.amount == Decimal("0.42")          # 80k x 3/M + 12k x 15/M
    reserve(db, **CALL)
    with pytest.raises(BudgetExhausted):
        reserve(db, **CALL)                     # 0.84 + 0.42 > 1.00


def test_settle_counts_actual_and_release_frees(db):
    setup(db, limit="1.00")
    a = reserve(db, **CALL)
    b = reserve(db, **CALL)
    settle(db, a, actual_amount=Decimal("0.10"), input_tokens=20_000, output_tokens=2_000)
    release(db, b)
    reserve(db, **CALL)
    reserve(db, **CALL)                         # 0.10 + 0.42 + 0.42 = 0.94
    with pytest.raises(BudgetRefused, match="not open"):
        settle(db, a, actual_amount=Decimal("0.10"), input_tokens=1, output_tokens=1)


def test_unresolved_call_keeps_counting_until_settled(db):
    setup(db, limit="1.00")
    a = reserve(db, **CALL)
    assert a.pricing_version == date(2026, 1, 1)
    mark_unresolved(db, a)
    reserve(db, **CALL)
    with pytest.raises(BudgetExhausted):
        reserve(db, **CALL)                     # 0.42 unresolved + 0.42 + 0.42 > 1.00
    settle(db, a, actual_amount=Decimal("0.05"), input_tokens=1000, output_tokens=100)
    reserve(db, **CALL)                         # 0.05 + 0.42 + 0.42 = 0.89
