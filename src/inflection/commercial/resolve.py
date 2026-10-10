"""Company-level event identity, dated versions, materiality and priority: pure functions, no database.

Event identity and lifecycle are ported from MakroGraph ``earnings_inflection/event_resolution.py``
(``resolve_events``, ``_find_predecessor``, ``_apply_lifecycle``, ``_absorb``, ``_amount_match``,
``_product_compatible``) at b31bdd0.  Rules kept:

* mentions merge on an order reference, or on the same named customer with an amount within 2%
  and a compatible product, within 400 days; a similar amount alone never merges orders;
* an unnamed customer with the same amount within 120 days may be the same order: a new event is
  kept and linked ``ambiguous_with`` the earlier one (counted once);
* "repeat / another / fresh order" of the same size is a new order;
* cancellation, partial cancellation, amendment, expiry and execution change the earlier order;
* a later, weaker wording ("we were L1") never downgrades an order.

New here: every change is a new version of the issuer's event (append-only, ``supersedes``), a
repetition only adds context evidence, a mention is compared only with events public before it
(an older disclosure read later is recorded as ``EARLIER_DISCLOSURE``), and the other commercial
families (qualification, commercial start, capacity, ...) form streams keyed by customer, facility
or product, so a plant moving from funded plan to commercial production is one event.
"""

from __future__ import annotations

import copy
import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Optional

from ..counterparty import same_counterparty
from ..units import Money
from . import vocabulary as V
from .extract import Mention

TOL = Decimal(V.POLICY["amount_tolerance"])
RANK = V.STAGE_RANK
_STOP = {"the", "of", "for", "and", "a", "an", "to", "kv", "supply", "order", "orders", "plant", "unit", "facility"}


@dataclass
class EventState:
    """The latest version of one issuer event, as resolution sees it."""
    event_id: str
    issuer_id: str
    family: str
    event_type: str
    first_public_at: datetime
    version_id: str = ""
    version_no: int = 0
    stage: str = "UNKNOWN"
    observation: str = "OBSERVED"
    amount: Optional[Money] = None
    original_amount: Optional[Money] = None
    basis: str = "UNQUANTIFIED"
    counterparty: str = ""                  # named customers only
    facility: str = ""
    stream: str = ""                        # product or segment
    relationship: str = "UNKNOWN"
    ownership_scope: str = "UNKNOWN"
    deadline: Optional[date] = None
    details: dict = field(default_factory=dict)
    artifacts: set = field(default_factory=set)
    published_at: Optional[datetime] = None  # disclosure behind the latest version

    def snapshot(self) -> "EventState":
        return copy.deepcopy(self)


@dataclass
class Placement:
    outcome: str                            # NEW | REVISION | REPETITION | EARLIER_DISCLOSURE | NOT_AN_EVENT
    event: Optional[EventState] = None      # state after the change (a copy)
    novelty: Optional[str] = None           # NEW | REVISION | HISTORY_UNAVAILABLE for new versions
    supersedes: Optional[str] = None        # previous version id
    previous_stage: Optional[str] = None
    relation: str = "SUPPORTS"
    note: str = ""


# ---------------------------------------------------------------- matching helpers (ported)

def amount_match(a: Optional[Money], b: Optional[Money], tol: Decimal = TOL) -> bool:
    if a is None or b is None or a.currency != b.currency:
        return False
    x, y = a.to_base(), b.to_base()
    hi = max(abs(x), abs(y))
    return hi > 0 and abs(x - y) / hi <= tol


def _tokens(p: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (p or "").lower()) if t not in _STOP and len(t) > 1}


def compatible(a: str, b: str) -> bool:
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return True                         # one side silent: not a contradiction
    return len(ta & tb) / min(len(ta), len(tb)) >= 0.5


def _named(m: Mention) -> str:
    return m.counterparty if m.counterparty_named else ""


def _stream(m: Mention) -> str:
    return m.details.get("product") or m.details.get("segment") or ""


def _gap(evt: EventState, at: datetime) -> timedelta:
    return at - evt.first_public_at


def _deadline(m: Mention) -> Optional[date]:
    d = m.details.get("deadline")
    return date.fromisoformat(d) if d else None


# ---------------------------------------------------------------- the resolver

class Resolver:
    """Places one issuer's mentions, oldest first, onto that issuer's events."""

    def __init__(self, issuer_id: str, events: Optional[list[EventState]] = None):
        self.issuer_id = issuer_id
        self.events: list[EventState] = list(events or [])

    # -- public

    def place(self, m: Mention, at: datetime, artifact: str) -> Placement:
        if m.modality == "NEGATED":
            return Placement("NOT_AN_EVENT", note="negated")
        if m.family == "ORDER":
            if m.lifecycle in ("CANCELLED", "EXPIRED", "AMENDED", "EXECUTED"):
                if m.modality != "REALIZED":
                    return Placement("NOT_AN_EVENT", note="lifecycle change stated as possible or expected")
                return self._lifecycle(m, at, artifact)
            return self._order(m, at, artifact)
        return self._stream_event(m, at, artifact)

    # -- orders

    def _orders(self, at: datetime, before: bool = True) -> list[EventState]:
        return [e for e in self.events if e.family == "ORDER"
                and ((e.first_public_at <= at) if before else (e.first_public_at > at))]

    def _find_order(self, m: Mention, cands: list[EventState], at: datetime, artifact: str
                    ) -> tuple[Optional[EventState], list[EventState]]:
        target, ambiguous = None, []
        cp = _named(m)
        ref = m.details.get("reference_id")
        for evt in sorted(cands, key=lambda e: e.first_public_at, reverse=True):
            if evt.stage == "CANCELLED" and evt.original_amount is None and evt.amount is None:
                continue                                 # an unlinked lifecycle note
            if ref and evt.details.get("reference_id"):
                if ref == evt.details["reference_id"]:
                    return evt, []
                continue                                 # different references: different orders
            if abs(_gap(evt, at)) > timedelta(days=V.POLICY["max_gap_days"]):
                continue
            if not compatible(evt.stream, _stream(m)):
                continue
            same = same_counterparty(evt.counterparty, cp)
            if same is False:
                continue
            same_doc = artifact in evt.artifacts and (same is True or (m.amount is None) == (evt.original_amount is None))
            if m.amount is not None and (evt.amount is not None or evt.original_amount is not None):
                if not (amount_match(evt.original_amount, m.amount) or amount_match(evt.amount, m.amount)):
                    continue
            elif not same_doc:
                # one side unquantified: the same order only when the named customer agrees and the
                # wording advances it (L1 -> award), never on a bare retelling from another filing
                progresses = RANK.get(m.stage, 0) > RANK.get(evt.stage, 0)
                if not (same is True and progresses
                        and _gap(evt, at) <= timedelta(days=V.POLICY["ambiguous_window_days"])):
                    continue
            if m.details.get("distinct_marker") and not evt.details.get("distinct_marker") and not same_doc:
                continue                                 # "repeat order" of the same size: a new order
            if same is True or same_doc:
                return evt, []
            if abs(_gap(evt, at)) <= timedelta(days=V.POLICY["ambiguous_window_days"]):
                ambiguous.append(evt)                    # identity cannot be established
        return target, ambiguous

    def _order(self, m: Mention, at: datetime, artifact: str) -> Placement:
        target, ambiguous = self._find_order(m, self._orders(at), at, artifact)
        if target is not None:
            return self._absorb(target, m, at, artifact)
        later, _ = self._find_order(m, self._orders(at, before=False), at, artifact)
        if later is not None:
            return self._earlier(later, m, at, artifact)
        evt = self._new(m, at, artifact)
        cp = _named(m)
        if cp:
            earlier = [e for e in self.events if e is not evt and same_counterparty(e.counterparty, cp) is True
                       and e.first_public_at <= at]
            orders = [e for e in earlier if e.family == "ORDER" and RANK.get(e.stage, 0) >= RANK["BINDING_DEMAND"]]
            if m.details.get("repeat_marker") and orders and m.modality == "REALIZED":
                evt.stage = "REPEAT_SHIPMENT"
                evt.details["repeat_of"] = orders[-1].event_id
            qual = [e for e in earlier if e.family in ("QUALIFICATION", "ORDER") and e is not evt
                    and RANK.get(e.stage, 0) < RANK.get(evt.stage, 0)]
            if qual:
                evt.details["follows"] = [e.event_id for e in qual][-3:]
        if ambiguous:
            evt.details["ambiguous_with"] = [e.event_id for e in ambiguous]
            for a in ambiguous:
                a.details.setdefault("ambiguous_with", []).append(evt.event_id)
        return Placement("NEW", evt.snapshot(), "NEW", note="ambiguous with an earlier order" if ambiguous else "")

    def _predecessor(self, m: Mention, at: datetime, artifact: str) -> tuple[Optional[EventState], str]:
        ref = m.details.get("reference_id")
        live = [e for e in self._orders(at) if e.stage != "CANCELLED"]
        if ref:
            hit = [e for e in live if e.details.get("reference_id") == ref]
            if len(hit) == 1:
                return hit[0], ""
        cp = _named(m)
        cands = [e for e in live if not cp or same_counterparty(e.counterparty, cp) is True]
        if m.amount is not None and len(cands) > 1 and m.lifecycle != "AMENDED":
            cands = [e for e in cands if amount_match(e.original_amount, m.amount)
                     or amount_match(e.amount, m.amount)] or cands
        if _stream(m) and len(cands) > 1:
            cands = [e for e in cands if compatible(e.stream, _stream(m))] or cands
        if len(cands) > 1:
            cands = [e for e in cands if artifact in e.artifacts] or cands
        if len(cands) == 1 and (cp or m.amount is not None or artifact in cands[0].artifacts):
            return cands[0], ""
        return None, ("earlier order not on record" if not cands else
                      f"earlier order ambiguous among {len(cands)} orders")

    def _lifecycle(self, m: Mention, at: datetime, artifact: str) -> Placement:
        target, why = self._predecessor(m, at, artifact)
        if target is None:
            if m.lifecycle == "AMENDED":
                return Placement("NOT_AN_EVENT", note=f"amendment: {why}")
            evt = self._new(m, at, artifact)
            evt.details["unresolved"] = why
            if m.lifecycle in ("CANCELLED", "EXPIRED"):
                evt.stage, evt.amount, evt.original_amount, evt.basis = "CANCELLED", None, None, "UNQUANTIFIED"
                evt.details["cancelled_amount"] = str(m.amount.value) if m.amount else None
            return Placement("NEW", evt.snapshot(), "HISTORY_UNAVAILABLE", note=why)
        prev_version, prev_stage = target.version_id, target.stage
        current = target.amount
        note = ""
        if m.lifecycle == "CANCELLED":
            partial = (m.amount is not None and current is not None and m.amount.currency == current.currency
                       and m.amount.to_base() < current.to_base() * (1 - TOL))
            if partial:
                remaining = (current.to_base() - m.amount.to_base()) / current.scale.factor
                target.amount = Money(remaining, current.currency, current.scale, "after partial cancellation")
                target.details["cancelled_amount"] = str(m.amount.value) + " " + m.amount.scale.value
                note = "partially cancelled"
            else:
                target.amount = Money(Decimal(0), current.currency, current.scale, "cancelled") if current else None
                target.stage = "CANCELLED"
                note = "cancelled"
        elif m.lifecycle == "EXPIRED":
            target.stage = "CANCELLED"
            target.details["expired"] = True
            note = "expired"
        elif m.lifecycle == "AMENDED":
            if m.amount is not None:
                target.details["amended_from"] = (f"{current.value} {current.scale.value}" if current else None)
                target.amount = m.amount
                if target.basis == "UNQUANTIFIED":
                    target.basis = "FIRM"
                note = "value amended"
            else:
                target.details["amendment_unquantified"] = True
                note = "terms amended; value not stated"
        elif m.lifecycle == "EXECUTED":
            if RANK.get(target.stage, 0) >= RANK["COMMERCIAL_SHIPMENT"]:
                return self._repeat(target, m, artifact)
            target.stage = "COMMERCIAL_SHIPMENT"
            target.observation = "OBSERVED"
            note = "execution / delivery reported"
        self._advance(target, m, at, artifact)
        return Placement("REVISION", target.snapshot(), "REVISION", prev_version, prev_stage, note=note)

    # -- shared

    def _new(self, m: Mention, at: datetime, artifact: str) -> EventState:
        evt = EventState(
            event_id=str(uuid.uuid4()), issuer_id=self.issuer_id, family=m.family, event_type=m.event_type,
            first_public_at=at, stage=m.stage, observation=m.observation_status, amount=m.amount,
            original_amount=m.amount, basis=m.amount_basis, counterparty=_named(m),
            facility=m.details.get("facility", ""), stream=_stream(m), relationship=m.relationship,
            ownership_scope=m.ownership_scope, deadline=_deadline(m),
            details={k: v for k, v in m.details.items() if k not in ("cue",)})
        if not m.counterparty_named and m.family in ("ORDER", "QUALIFICATION"):
            evt.details.setdefault("unresolved_fields", []).append("customer identity not disclosed")
        self._advance(evt, m, at, artifact)
        self.events.append(evt)
        return evt

    def _advance(self, evt: EventState, m: Mention, at: datetime, artifact: str) -> None:
        evt.version_no += 1
        evt.version_id = str(uuid.uuid4())
        evt.artifacts.add(artifact)
        evt.published_at = at

    def _repeat(self, evt: EventState, m: Mention, artifact: str) -> Placement:
        evt.artifacts.add(artifact)
        return Placement("REPETITION", evt.snapshot(), relation="CONTEXT", note="restates a known event")

    def _earlier(self, evt: EventState, m: Mention, at: datetime, artifact: str) -> Placement:
        evt.first_public_at = at
        evt.artifacts.add(artifact)
        return Placement("EARLIER_DISCLOSURE", evt.snapshot(), relation="CONTEXT",
                         note="an earlier disclosure of this event, read after later ones")

    def _absorb(self, evt: EventState, m: Mention, at: datetime, artifact: str) -> Placement:
        """A known event mentioned again: a new version only for a substantive change (stage advance,
        forecast now observed, amount or customer newly disclosed); otherwise a repetition."""
        changes = []
        prev_version, prev_stage = evt.version_id, evt.stage
        if (m.modality == "REALIZED" and evt.stage in RANK and m.stage in RANK
                and RANK[m.stage] > RANK[evt.stage]):
            evt.stage = m.stage
            changes.append(f"stage {prev_stage} -> {m.stage}")
            if m.amount is not None and m.amount_basis not in ("UNQUANTIFIED",):
                evt.amount, evt.basis = m.amount, m.amount_basis
        if evt.observation == "FORECAST" and m.observation_status == "OBSERVED" and RANK.get(m.stage, 0) >= RANK.get(evt.stage, 0):
            evt.observation = "OBSERVED"
            changes.append("now observed")
        if evt.amount is None and m.amount is not None:
            evt.amount, evt.original_amount, evt.basis = m.amount, evt.original_amount or m.amount, m.amount_basis
            changes.append("amount disclosed")
        if not evt.counterparty and m.counterparty_named:
            evt.counterparty = m.counterparty
            evt.details["unresolved_fields"] = [f for f in evt.details.get("unresolved_fields", [])
                                                if f != "customer identity not disclosed"]
            changes.append("customer named")
        if m.family == "CAPACITY" and m.details.get("commissioned") and not evt.details.get("commissioned"):
            evt.details["commissioned"] = True
            evt.observation = "OBSERVED"
            changes.append("commissioned")
        # terms fill in without making a version on their own
        for k in ("duration_months", "delivery_window", "payment_terms", "termination_terms", "reference_id",
                  "product", "tax_basis", "customer_geography", "capacity", "deadline", "funding_cue"):
            if m.details.get(k) and (not evt.details.get(k) or evt.details.get(k) == "UNKNOWN"):
                evt.details[k] = m.details[k]
                if k == "deadline":
                    evt.deadline = _deadline(m)
        rel_rank = {"UNKNOWN": 0, "ISSUER_ASSERTED_UNRELATED": 1, "INDEPENDENTLY_SUPPORTED_UNRELATED": 2,
                    "CONFIRMED_RELATED": 3}
        if rel_rank[m.relationship] > rel_rank[evt.relationship]:
            if m.relationship == "CONFIRMED_RELATED":
                changes.append("related party")
            evt.relationship = m.relationship
        if not changes:
            return self._repeat(evt, m, artifact)
        self._advance(evt, m, at, artifact)
        return Placement("REVISION", evt.snapshot(), "REVISION", prev_version, prev_stage, note="; ".join(changes))

    # -- streams (qualification, commercial start, capacity, ...)

    def _stream_match(self, m: Mention, cands: list[EventState], at: datetime, artifact: str) -> Optional[EventState]:
        cp, fac, stream = _named(m), m.details.get("facility", ""), _stream(m)
        types = {m.event_type}
        if m.family == "COMMERCIAL_START" and fac:
            types.add("CAPACITY")                    # production starts at a plant that was a capacity plan
        best = None
        for evt in sorted(cands, key=lambda e: e.first_public_at, reverse=True):
            if evt.event_type not in types:
                continue
            if artifact in evt.artifacts and evt.event_type == m.event_type:
                return evt
            if abs(_gap(evt, at)) > timedelta(days=V.POLICY["stream_window_days"]):
                continue
            keys_m = [k for k in (cp, fac, stream) if k]
            keys_e = [k for k in (evt.counterparty, evt.facility, evt.stream) if k]
            if cp and evt.counterparty:
                if same_counterparty(evt.counterparty, cp) is True:
                    return evt
                continue
            if fac and evt.facility:
                if compatible(evt.facility, fac):
                    return evt
                continue
            if evt.event_type != m.event_type:
                continue
            if stream and evt.stream:
                if compatible(evt.stream, stream):
                    return evt
                continue
            if not keys_m and not keys_e and abs(_gap(evt, at)) <= timedelta(days=V.POLICY["ambiguous_window_days"]):
                best = best or evt                   # an unkeyed restatement ("debt-free") soon after
        return best

    def _stream_event(self, m: Mention, at: datetime, artifact: str) -> Placement:
        before = [e for e in self.events if e.family != "ORDER" and e.first_public_at <= at]
        target = self._stream_match(m, before, at, artifact)
        if target is not None:
            if target.event_type != m.event_type and RANK.get(m.stage, 0) > RANK.get(target.stage, 0) \
                    and m.modality == "REALIZED":
                target.details["commercial_start"] = True
            return self._absorb(target, m, at, artifact)
        after = [e for e in self.events if e.family != "ORDER" and e.first_public_at > at]
        later = self._stream_match(m, after, at, artifact)
        if later is not None:
            return self._earlier(later, m, at, artifact)
        return Placement("NEW", self._new(m, at, artifact).snapshot(), "NEW")


# ---------------------------------------------------------------- materiality (spec 18.2)

@dataclass(frozen=True)
class Materiality:
    status: str                 # MATERIAL_POTENTIAL | MATERIALITY_UNKNOWN | IMMATERIAL
    reason: str
    ratio_total: Optional[Decimal] = None
    ratio_annualised: Optional[Decimal] = None
    band: int = 1               # 3 material, 2 large but horizon unknown, 1 unknown, 0 immaterial


def materiality(evt: EventState, annual_revenue: Optional[Decimal]) -> Materiality:
    """Annualised executable revenue against comparable annual revenue.  Ceilings, MoUs, L1 bids,
    capacity, capex and foreign-currency amounts never count (no FX conversion is done)."""
    if evt.family != "ORDER":
        return Materiality("MATERIALITY_UNKNOWN", "not a revenue commitment; magnitude needs research")
    if evt.amount is None:
        return Materiality("MATERIALITY_UNKNOWN", "order value not disclosed")
    if evt.basis not in ("FIRM", "GUARANTEED_MINIMUM", "EXECUTABLE_RELEASE"):
        return Materiality("MATERIALITY_UNKNOWN", f"{evt.basis.lower()} value is not committed revenue")
    if evt.amount.currency != "INR":
        return Materiality("MATERIALITY_UNKNOWN", f"value in {evt.amount.currency}; no FX conversion")
    if not annual_revenue or annual_revenue <= 0:
        return Materiality("MATERIALITY_UNKNOWN", "no comparable annual revenue on record by this date")
    total = evt.amount.to_base()
    ratio_total = (total / annual_revenue).quantize(Decimal("0.0001"))
    if ratio_total <= Decimal(V.POLICY["immaterial_ratio"]):
        return Materiality("IMMATERIAL", f"whole order is {ratio_total:.2%} of annual revenue", ratio_total, None, 0)
    months = evt.details.get("duration_months")
    if not months:
        band = 2 if ratio_total >= Decimal(V.POLICY["material_ratio"]) else 1
        return Materiality("MATERIALITY_UNKNOWN", f"order is {ratio_total:.1%} of annual revenue; execution "
                           "period not stated", ratio_total, None, band)
    annual = total * min(Decimal(1), Decimal(12) / Decimal(months))
    ratio = (annual / annual_revenue).quantize(Decimal("0.0001"))
    if ratio >= Decimal(V.POLICY["material_ratio"]):
        return Materiality("MATERIAL_POTENTIAL", f"about {ratio:.1%} of annual revenue a year over {months} months",
                           ratio_total, ratio, 3)
    return Materiality("MATERIALITY_UNKNOWN", f"about {ratio:.1%} of annual revenue a year, below the "
                       f"{Decimal(V.POLICY['material_ratio']):.0%} mark", ratio_total, ratio, 1)


def execution_end(evt: EventState) -> Optional[date]:
    if evt.deadline:
        return evt.deadline
    months = evt.details.get("duration_months")
    if months and evt.published_at:
        start = evt.first_public_at.date()
        y, mth = divmod(start.month - 1 + int(months), 12)
        return date(start.year + y, mth + 1, min(start.day, 28))
    return None


# ---------------------------------------------------------------- priority (spec 18.2)

CLASS_ORDER = {"U0": 0, "P1": 1, "P2": 2, "P3": 3, "D": 4}


@dataclass
class Assessment:
    event: EventState
    novelty: str
    previous_stage: Optional[str]
    materiality: Materiality
    priority: str
    reason: str
    milestone: Optional[date]


def assess(evt: EventState, novelty: str, previous_stage: Optional[str], mat: Materiality,
           active_case: bool, equity_funded_recently: bool) -> Optional[Assessment]:
    """Priority class and reason for one new or changed event version; None for context-only families."""
    fam, stage = evt.family, evt.stage
    milestone = execution_end(evt)
    label = evt.event_type.replace("_", " ").lower()

    def a(cls: str, why: str) -> Assessment:
        return Assessment(evt, novelty, previous_stage, mat, cls, f"{label}: {why}", milestone)

    if fam in V.CONTEXT_FAMILIES:
        return None
    if active_case:
        return a("U0", "change for an issuer with an open research case")
    if stage == "CANCELLED":
        return a("P3", "order cancelled or expired; adverse, no open case to update")
    if evt.details.get("cancelled_amount") and novelty == "REVISION":
        return a("P3", "order partly cancelled")
    if evt.observation == "FORECAST":
        return a("P3", "stated as a plan or expectation, not observed")
    if fam == "CAPACITY":
        return a("P3", "capacity commissioned; demand evidence still needed" if evt.details.get("commissioned")
                 else "capacity plan without demand evidence stays on watch")
    if fam == "PRICING":
        return a("P3", "price change; retention and volume need evidence")
    if fam == "PRODUCT_LAUNCH":
        return a("P3", "launch without demand evidence")
    if fam == "DEBT_REDUCTION":
        if evt.details.get("funded_by_equity") or equity_funded_recently:
            return a("P3", "debt repaid from shareholder money is not operating debt reduction")
        if evt.details.get("rating_upgrade"):
            return a("P3", "credit rating change alone is a weak signal")
        if evt.amount is None:
            return a("P3", "finance-cost or debt-status statement; the financial route measures the change")
        return a("P2", "debt repaid; source of funds to verify")
    if fam == "LOSS_DRAG_REMOVAL":
        return a("P2", "loss-making activity removed")
    if evt.relationship == "CONFIRMED_RELATED":
        return a("P3", "related-party demand")
    if RANK.get(stage, 0) < RANK["QUALIFIED"]:
        return a("P3", "non-binding or unclear commitment" if fam == "ORDER" else "early stage")
    if mat.status == "IMMATERIAL":
        return a("P3", mat.reason)
    if mat.status == "MATERIAL_POTENTIAL":
        if milestone:
            return a("P1", f"{stage.lower().replace('_', ' ')}, {mat.reason}, next milestone {milestone.isoformat()}")
        return a("P2", f"{mat.reason}; no dated milestone")
    return a("P2", f"{stage.lower().replace('_', ' ')}; {mat.reason}")


def evaluation(items: list[Assessment], issuer_id: str, as_of: datetime) -> Optional[dict]:
    """One candidate evaluation for an issuer's changes from one filing (spec 18.3: one issuer-level
    case, not one per filing).  Ranking within a class: milestone soon, stage, materiality band,
    waiting time (earlier first), then a deterministic hash."""
    items = [i for i in items if i is not None]
    if not items:
        return None
    items.sort(key=lambda i: (CLASS_ORDER[i.priority], -RANK.get(i.event.stage, 0), -i.materiality.band))
    top = items[0]
    cls = top.priority
    outcome = "ADMIT" if cls in ("U0", "P1", "P2") else "DEFER"
    allocation = {"U0": "UPDATE", "P1": "RANKED", "P2": "RANKED"}.get(cls, "NONE")
    mat_order = {"MATERIAL_POTENTIAL": 0, "MATERIALITY_UNKNOWN": 1, "IMMATERIAL": 2}
    best_mat = min((i.materiality.status for i in items), key=mat_order.get)
    soon = top.milestone is not None and top.milestone <= (as_of + timedelta(days=365)).date()
    tie = hashlib.sha256(f"{issuer_id}|{V.RULES_VERSION}".encode()).hexdigest()[:16]
    funding = "FUNDED" if any(i.event.family == "CAPACITY" and i.event.stage == "FUNDED_PLAN" for i in items) else None
    return dict(
        priority_class=cls, outcome=outcome, queue_allocation=allocation, materiality=best_mat, funding=funding,
        reasons=[i.reason for i in items],
        ranking=[CLASS_ORDER[cls], 0 if soon else 1, -RANK.get(top.event.stage, 0), -top.materiality.band,
                 as_of.isoformat(), tie],
        items=items)
