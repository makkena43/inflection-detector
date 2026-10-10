"""Amounts with currency, magnitude scale and physical unit kept apart (spec section 17).

INR crore is a presentation convention only.  Amounts are stored as
(value, currency, scale) with the original text, converted to base units
only for arithmetic, and never converted between currencies here: there is
no FX source, so a mixed-currency calculation is an error, not a guess.

Amount parsing is ported from MakroGraph ``earnings_inflection/extraction.py``
``parse_inr`` / ``parse_usd`` at b31bdd0 (see docs/reuse_inventory.md), changed
to keep currency and scale separate and to use Decimal.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional


class Scale(str, Enum):
    UNITS = "UNITS"
    THOUSAND = "THOUSAND"
    LAKH = "LAKH"
    MILLION = "MILLION"
    CRORE = "CRORE"
    BILLION = "BILLION"

    @property
    def factor(self) -> Decimal:
        return _FACTOR[self]


_FACTOR = {Scale.UNITS: Decimal(1), Scale.THOUSAND: Decimal(10) ** 3, Scale.LAKH: Decimal(10) ** 5,
           Scale.MILLION: Decimal(10) ** 6, Scale.CRORE: Decimal(10) ** 7, Scale.BILLION: Decimal(10) ** 9}


class UnitError(ValueError):
    pass


@dataclass(frozen=True)
class Money:
    value: Decimal
    currency: str               # ISO 4217, e.g. "INR", "USD"
    scale: Scale
    original_text: str = ""

    def to_base(self) -> Decimal:
        return self.value * self.scale.factor

    def to(self, scale: Scale) -> "Money":
        return Money(self.to_base() / scale.factor, self.currency, scale, self.original_text)


def same_currency(*amounts: Money) -> str:
    currencies = {a.currency for a in amounts}
    if len(currencies) != 1:
        raise UnitError(f"mixed currencies {sorted(currencies)}: no conversion is performed")
    return currencies.pop()


def add(*amounts: Money, scale: Scale = Scale.CRORE) -> Money:
    cur = same_currency(*amounts)
    return Money(sum((a.to_base() for a in amounts), Decimal(0)) / scale.factor, cur, scale)


# --- parsing ---------------------------------------------------------------

_SCALE_WORDS = {
    "crore": Scale.CRORE, "crores": Scale.CRORE, "cr": Scale.CRORE, "crs": Scale.CRORE,
    "lakh": Scale.LAKH, "lakhs": Scale.LAKH, "lac": Scale.LAKH, "lacs": Scale.LAKH,
    "mn": Scale.MILLION, "million": Scale.MILLION, "bn": Scale.BILLION, "billion": Scale.BILLION,
    "thousand": Scale.THOUSAND,
}
_INR = r"(?:rs\.?|inr|₹|rupees)"
_USD = r"(?:us\$|usd|\$)"
_NUMBER = r"(\d[\d,]*(?:\.\d+)?)"
_SCALE_RE = r"(crores?|cr\.?|crs|lakhs?|lacs?|lac|mn|million|bn|billion|thousand)"
_AMOUNT = re.compile(rf"(?:({_INR})|({_USD}))?\s*{_NUMBER}\s*{_SCALE_RE}\b", re.I)


def parse_amount(text: str) -> Optional[Money]:
    """First amount in ``text`` with an explicit scale word.

    Without a currency marker only "crore"/"lakh" are unambiguous money in
    Indian filings ("1 million" may be doses or tonnes), so those return None.
    """
    for m in _AMOUNT.finditer(text or ""):
        inr, usd, num, scale_word = m.groups()
        scale = _SCALE_WORDS[scale_word.lower().rstrip(".")]
        if usd:
            currency = "USD"
        elif inr or scale in (Scale.CRORE, Scale.LAKH):
            currency = "INR"
        else:
            continue
        return Money(Decimal(num.replace(",", "")), currency, scale, m.group(0).strip())
    return None


# --- growth ---------------------------------------------------------------

@dataclass(frozen=True)
class Growth:
    pct: Optional[Decimal]
    reason: str             # "ok" or why no meaningful percentage exists


def growth(current: Money, base: Money, min_base: Optional[Money] = None) -> Growth:
    """Percentage change, refusing zero, negative or near-zero bases (section 15 test 7)."""
    same_currency(current, base, *([min_base] if min_base else []))
    b = base.to_base()
    if b == 0:
        return Growth(None, "zero base: percentage growth is undefined")
    if b < 0:
        return Growth(None, "negative base: percentage growth is not meaningful; report the absolute change")
    if min_base is not None and b < min_base.to_base():
        return Growth(None, "base below materiality floor: percentage growth would mislead")
    return Growth((current.to_base() / b - 1) * 100, "ok")
