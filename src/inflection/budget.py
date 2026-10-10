"""Persistent, atomic spend reservations (spec section 10).

Replaces MakroGraph's process-local ``Budget`` counters (see
docs/reuse_inventory.md).  Every paid call reserves its worst-case cost in
``budget_ledger`` before dispatch, inside a transaction that locks the month's
budget row, so two workers cannot both spend the last of the budget.

Fails closed: no budget row, paid calls disabled, or no price for the model
all refuse the reservation.  Exhaustion raises ``BudgetExhausted``; callers
move the case to DEFERRED_BUDGET and keep their work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

MTOK = Decimal(1_000_000)


class BudgetRefused(RuntimeError):
    pass


class BudgetExhausted(BudgetRefused):
    pass


@dataclass(frozen=True)
class Reservation:
    entry_id: str
    amount: Decimal
    currency: str


def _month(d: date) -> date:
    return d.replace(day=1)


def reserve(conn, *, on: date, provider: str, model: str, max_input_tokens: int, max_output_tokens: int,
            case_id: Optional[str] = None) -> Reservation:
    """Reserve the worst-case cost of one bounded call.  ``conn`` is a psycopg connection."""
    month = _month(on)
    with conn.transaction():
        cur = conn.execute(
            "SELECT currency, limit_amount, paid_calls_enabled FROM budgets WHERE budget_month = %s FOR UPDATE",
            (month,))
        row = cur.fetchone()
        if row is None:
            raise BudgetRefused(f"no budget set for {month:%Y-%m}; paid calls stay off")
        currency, limit_amount, enabled = row
        if not enabled:
            raise BudgetRefused("paid calls are disabled for this month")
        price = conn.execute(
            "SELECT input_per_mtok, output_per_mtok FROM model_prices "
            "WHERE provider = %s AND model = %s AND currency = %s AND effective_from <= %s "
            "ORDER BY effective_from DESC LIMIT 1",
            (provider, model, currency, on)).fetchone()
        if price is None:
            raise BudgetRefused(f"no {currency} price recorded for {provider}/{model}; refusing to guess")
        amount = (Decimal(max_input_tokens) * price[0] + Decimal(max_output_tokens) * price[1]) / MTOK
        committed = conn.execute(
            "SELECT coalesce(sum(CASE status WHEN 'RESERVED' THEN reserved_amount "
            "                                WHEN 'SETTLED' THEN actual_amount END), 0) "
            "FROM budget_ledger WHERE budget_month = %s", (month,)).fetchone()[0]
        if committed + amount > limit_amount:
            raise BudgetExhausted(f"reserving {amount} {currency} would exceed the {limit_amount} limit "
                                  f"({committed} already committed)")
        entry_id = conn.execute(
            "INSERT INTO budget_ledger (budget_month, case_id, provider, model, status, reserved_amount) "
            "VALUES (%s, %s, %s, %s, 'RESERVED', %s) RETURNING entry_id",
            (month, case_id, provider, model, amount)).fetchone()[0]
    return Reservation(str(entry_id), amount, currency)


def settle(conn, reservation: Reservation, *, actual_amount: Decimal, input_tokens: int, output_tokens: int,
           fee_breakdown: Optional[dict] = None) -> None:
    """Record actual usage.  An overrun is recorded as-is and counts against later reservations."""
    from psycopg.types.json import Jsonb
    with conn.transaction():
        n = conn.execute(
            "UPDATE budget_ledger SET status = 'SETTLED', actual_amount = %s, input_tokens = %s, "
            "output_tokens = %s, fee_breakdown = %s, settled_at = now() "
            "WHERE entry_id = %s AND status = 'RESERVED'",
            (actual_amount, input_tokens, output_tokens, Jsonb(fee_breakdown or {}), reservation.entry_id)).rowcount
        if n != 1:
            raise BudgetRefused(f"reservation {reservation.entry_id} is not open")


def release(conn, reservation: Reservation) -> None:
    """Cancel a reservation whose call was never made."""
    with conn.transaction():
        conn.execute("UPDATE budget_ledger SET status = 'RELEASED' WHERE entry_id = %s AND status = 'RESERVED'",
                     (reservation.entry_id,))
