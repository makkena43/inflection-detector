"""Dated issuer / security identity.

Ported concepts from MakroGraph ``earnings_inflection/identity.py`` at b31bdd0
(see docs/reuse_inventory.md).  Symbols are not identities: NSE renames,
mergers and SME migrations mean a symbol can point to different issuers over
time.  Differences from the original:

* an unknown symbol resolves to *nothing*.  MakroGraph fell back to
  ``symbol_assumed_stable``; the spec forbids that for investment decisions
  and audited replay, so here it is an explicit unresolved result;
* ISIN is part of every security record;
* replay modes come from ``states.RunMode``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from .states import RunMode

NSE_MAINBOARD_EQUITY_SERIES = {"EQ", "BE", "BZ"}
NSE_SME_SERIES = {"SM", "ST", "SZ"}
# Anything else (warrants, partly paid, debt, RR, IV ...) is not the operating equity.


class IdentityError(ValueError):
    pass


@dataclass(frozen=True)
class Alias:
    value: str                      # NSE symbol or BSE scrip code
    exchange: str                   # "NSE" | "BSE"
    isin: str
    issuer_id: str
    valid_from: date
    valid_to: Optional[date] = None
    series: str = ""
    recorded_at: Optional[datetime] = None   # when the system learned the mapping
    source: str = ""

    def covers(self, d: date) -> bool:
        return self.valid_from <= d and (self.valid_to is None or d <= self.valid_to)


@dataclass(frozen=True)
class Resolution:
    issuer_id: Optional[str]
    isin: Optional[str]
    basis: str          # "dated_alias" | "unresolved" | "mapping_not_known_by_cutoff"

    @property
    def resolved(self) -> bool:
        return self.issuer_id is not None


@dataclass
class IssuerRegistry:
    aliases: list[Alias] = field(default_factory=list)

    def resolve(self, value: str, exchange: str, on: date, mode: RunMode = RunMode.LIVE,
                cutoff: Optional[datetime] = None) -> Resolution:
        """Issuer holding ``value`` on ``exchange`` at date ``on``.

        In ACTUAL_SYSTEM_REPLAY the mapping must also have been recorded by ``cutoff``.
        Two different issuers matching is an error that needs review, never a guess.
        """
        v, ex = value.upper().strip(), exchange.upper()
        hits = [a for a in self.aliases if a.value.upper() == v and a.exchange == ex and a.covers(on)]
        if mode == RunMode.ACTUAL_SYSTEM_REPLAY:
            if cutoff is None:
                raise IdentityError("actual-system replay needs a cutoff")
            known = [a for a in hits if a.recorded_at is not None and a.recorded_at <= cutoff]
            if hits and not known:
                return Resolution(None, None, "mapping_not_known_by_cutoff")
            hits = known
        if not hits:
            return Resolution(None, None, "unresolved")
        issuers = {(a.issuer_id, a.isin) for a in hits}
        if len(issuers) > 1:
            raise IdentityError(f"ambiguous {ex}:{v} on {on}: {sorted(issuers)} (needs review)")
        issuer_id, isin = issuers.pop()
        return Resolution(issuer_id, isin, "dated_alias")


def is_operating_equity_series(series: Optional[str], allow_sme: bool = True) -> Optional[bool]:
    """True/False for a known series; ``None`` when unknown (treat as ambiguous, not as equity)."""
    if not series:
        return None
    s = series.upper().strip()
    if s in NSE_MAINBOARD_EQUITY_SERIES:
        return True
    if s in NSE_SME_SERIES:
        return allow_sme
    return False


def board_from(series: Optional[str] = None, board: str = "") -> str:
    if series and series.upper() in NSE_SME_SERIES:
        return "SME"
    if re.search(r"\bsme\b|emerge", board or "", re.I):
        return "SME"
    if (series and series.upper() in NSE_MAINBOARD_EQUITY_SERIES) or board:
        return "MAINBOARD"
    return "UNKNOWN"
