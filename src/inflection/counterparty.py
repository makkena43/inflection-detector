"""Counterparty names, relationship status and commitment strength.

Vocabulary and name-matching ported from MakroGraph
``earnings_inflection/counterparty.py`` and ``identity.py`` at b31bdd0 (see
docs/reuse_inventory.md).  Rules from the spec:

* an issuer statement never makes a relationship more than
  ISSUER_ASSERTED_UNRELATED;
* INDEPENDENTLY_SUPPORTED_UNRELATED needs a dated, attributable source
  available by the cutoff;
* UNKNOWN is not evidence of a shell company or fraud, and missing customer
  corroboration is recorded as such rather than guessed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Optional

from .states import RelationshipStatus


class CommitmentStrength(str, Enum):
    BINDING = "BINDING"             # PO, signed contract, accepted LoA with value
    PROVISIONAL = "PROVISIONAL"     # L1 bidder, LoI, selected but not awarded
    NON_BINDING = "NON_BINDING"     # MoU, framework, "in discussions"
    NOT_APPLICABLE = "NOT_APPLICABLE"


_REL_RANK = {RelationshipStatus.UNKNOWN: 0, RelationshipStatus.ISSUER_ASSERTED_UNRELATED: 1,
             RelationshipStatus.INDEPENDENTLY_SUPPORTED_UNRELATED: 2, RelationshipStatus.CONFIRMED_RELATED: 3}


@dataclass(frozen=True)
class RelationshipEvidence:
    claim: str                      # "RELATED" | "UNRELATED"
    by_issuer: bool                 # the issuer's own statement?
    source: str
    as_of: date


def assess_relationship(evidence: list[RelationshipEvidence], cutoff: date
                        ) -> tuple[RelationshipStatus, list[str]]:
    """Strongest status the evidence available by ``cutoff`` supports, with the sources used."""
    status, used = RelationshipStatus.UNKNOWN, []
    for ev in evidence:
        if ev.as_of > cutoff:
            continue
        if ev.claim == "RELATED":
            cand = RelationshipStatus.CONFIRMED_RELATED
        elif ev.claim == "UNRELATED":
            cand = (RelationshipStatus.ISSUER_ASSERTED_UNRELATED if ev.by_issuer
                    else RelationshipStatus.INDEPENDENTLY_SUPPORTED_UNRELATED)
        else:
            raise ValueError(f"unknown relationship claim {ev.claim!r}")
        used.append(f"{ev.source} ({ev.as_of.isoformat()})")
        if _REL_RANK[cand] > _REL_RANK[status]:
            status = cand
    return status, used


_SUFFIXES = re.compile(
    r"\b(?:private|pvt|public|limited|ltd|llp|inc|incorporated|corp|corporation|company|co|plc|gmbh|ag|sa|bv)\b\.?",
    re.I,
)
_LEGAL_FORM = re.compile(r"\b(?:private|pvt|public|limited|ltd|llp|inc|incorporated|plc|gmbh|ag|sa|bv)\b\.?", re.I)


def normalize_counterparty(name: str) -> str:
    n = (name or "").lower().replace("&", " and ")
    n = _SUFFIXES.sub(" ", n)
    n = re.sub(r"[^a-z0-9 ]+", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _acronym(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]+", " ", _LEGAL_FORM.sub(" ", (name or "").lower().replace("&", " and ")))
    return "".join(w[0] for w in n.split() if w not in {"of", "and", "the"})


def same_counterparty(a: str, b: str) -> Optional[bool]:
    """True/False when both are named; ``None`` when either is unknown."""
    na, nb = normalize_counterparty(a), normalize_counterparty(b)
    if not na or not nb:
        return None
    if na == nb:
        return True
    if (len(na.split()) == 1 and na == _acronym(b)) or (len(nb.split()) == 1 and nb == _acronym(a)):
        return True
    ta, tb = set(na.split()), set(nb.split())
    return len(ta & tb) / max(1, min(len(ta), len(tb))) >= 0.8
