"""Deterministic earnings bridge (spec section 7).

The model proposes inputs and evidence; this module computes the bridge.  It
never fills gaps: a missing or dimensionally wrong input is a validation
error, not a default.  Every money input carries its currency and magnitude
scale (spec section 17); arithmetic runs in base units, all money must share
one currency (no FX conversion), and results are presented in a chosen scale.

Per period and scenario:
  1. baseline attributable profit (normalised for one-offs)
  2. incremental revenue per stream: units x realisation, an evidenced contract
     schedule, or comparable revenue x incremental margin (margin recovery)
  3. incremental EBITDA less ramp costs, depreciation, interest, tax,
     cannibalisation, corporate costs and minorities
  4. attributable profit / diluted shares (issued equity, warrants,
     convertibles, scenario financing)
  5. cash needs: working capital, capex, debt service vs available funding
  6. EPS x a valuation range, with downside compression and a no-rerating check
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum
from typing import Optional

from .states import InputStatus, Scenario
from .units import Scale

ENGINE_VERSION = "bridge-2"


class Kind(str, Enum):
    MONEY = "MONEY"                         # currency + scale
    SHARES = "SHARES"                       # scale
    PERCENT = "PERCENT"
    MULTIPLE = "MULTIPLE"
    PER_SHARE = "PER_SHARE"                 # currency per share, scale UNITS
    PHYSICAL = "PHYSICAL"                   # physical_unit
    MONEY_PER_PHYSICAL = "MONEY_PER_PHYSICAL"   # currency + scale per physical_unit


class BridgeValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    kind: Kind
    status: InputStatus
    evidence_ids: tuple[str, ...] = ()
    currency: Optional[str] = None
    scale: Scale = Scale.UNITS
    physical_unit: Optional[str] = None

    def base(self) -> Decimal:
        return self.value * self.scale.factor

    @staticmethod
    def _make(value, kind, status, evidence_ids=(), **kw) -> "Quantity":
        return Quantity(Decimal(str(value)), kind, InputStatus(status), tuple(evidence_ids), **kw)

    @classmethod
    def money(cls, value, currency: str, scale: Scale, status, evidence_ids=()):
        return cls._make(value, Kind.MONEY, status, evidence_ids, currency=currency, scale=Scale(scale))

    @classmethod
    def shares(cls, value, scale: Scale, status, evidence_ids=()):
        return cls._make(value, Kind.SHARES, status, evidence_ids, scale=Scale(scale))

    @classmethod
    def percent(cls, value, status, evidence_ids=()):
        return cls._make(value, Kind.PERCENT, status, evidence_ids)

    @classmethod
    def multiple(cls, value, status, evidence_ids=()):
        return cls._make(value, Kind.MULTIPLE, status, evidence_ids)

    @classmethod
    def per_share(cls, value, currency: str, status, evidence_ids=()):
        return cls._make(value, Kind.PER_SHARE, status, evidence_ids, currency=currency)

    @classmethod
    def physical(cls, value, unit: str, status, evidence_ids=()):
        return cls._make(value, Kind.PHYSICAL, status, evidence_ids, physical_unit=unit)

    @classmethod
    def realisation(cls, value, currency: str, scale: Scale, per_unit: str, status, evidence_ids=()):
        return cls._make(value, Kind.MONEY_PER_PHYSICAL, status, evidence_ids, currency=currency,
                         scale=Scale(scale), physical_unit=per_unit)


@dataclass(frozen=True)
class Stream:
    """One prospective incremental earnings stream (at most three per case)."""
    name: str
    kind: str                                   # "VOLUME" | "CONTRACT" | "MARGIN_RECOVERY"
    ebitda_margin: Optional[Quantity] = None    # percent; VOLUME and CONTRACT
    volume: Optional[Quantity] = None           # VOLUME: physical units in the period
    realisation: Optional[Quantity] = None      # VOLUME: money per volume unit
    contract_revenue: Optional[Quantity] = None # CONTRACT: revenue executed in this period
    comparable_revenue: Optional[Quantity] = None   # MARGIN_RECOVERY
    incremental_margin: Optional[Quantity] = None   # MARGIN_RECOVERY: percent points
    ramp_costs: Optional[Quantity] = None
    cannibalisation: Optional[Quantity] = None  # EBITDA lost elsewhere in the business
    overlaps_with: tuple[str, ...] = ()         # declared overlap with another stream -> rejected


@dataclass(frozen=True)
class Dilution:
    name: str                                   # e.g. "warrants 2027", "QIP scenario financing"
    shares: Quantity                            # weighted for the period
    cash_in: Optional[Quantity] = None


@dataclass(frozen=True)
class BridgeInputs:
    period: str
    scenario: Scenario
    baseline_attributable_profit: Quantity      # normalised
    streams: tuple[Stream, ...]
    depreciation: Quantity                      # incremental
    interest: Quantity                          # incremental
    corporate_costs: Quantity                   # incremental
    tax_rate: Quantity                          # percent
    minority_share: Quantity                    # percent of incremental profit
    basic_shares: Quantity                      # weighted average
    dilution: tuple[Dilution, ...]
    working_capital: Quantity
    capex: Quantity
    debt_service: Quantity
    available_funding: Quantity                 # cash + committed facilities
    pe_low: Quantity
    pe_high: Quantity
    downside_compression: Quantity              # percent cut to pe_low for the downside value
    current_price: Quantity                     # per share; its currency is the case currency
    current_pe: Optional[Quantity] = None       # sourced trailing multiple for the no-rerating check
    presentation_scale: Scale = Scale.CRORE


@dataclass
class BridgeResult:
    engine_version: str
    inputs_hash: str
    period: str
    scenario: str
    currency: str
    presentation_scale: str
    incremental_revenue: dict[str, str]
    incremental_ebitda: str
    incremental_pbt: str
    incremental_pat: str
    incremental_attributable: str
    baseline_attributable: str
    attributable_profit: str
    basic_shares: str
    diluted_shares: str
    baseline_eps: str
    eps: str
    value_low: str
    value_high: str
    value_compressed: str
    value_no_rerating: Optional[str]
    return_at_low_pct: str
    return_no_rerating_pct: Optional[str]
    cash_required: str
    funding_gap: str
    flags: list[str] = field(default_factory=list)


def _q(d: Decimal, places: str = "0.01") -> str:
    return str(d.quantize(Decimal(places), rounding=ROUND_HALF_EVEN))


def _hash(inputs: BridgeInputs) -> str:
    def default(o):
        if isinstance(o, Decimal):
            return str(o)
        if isinstance(o, Enum):
            return o.value
        raise TypeError(type(o))
    blob = json.dumps(asdict(inputs), default=default, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _check(errors: list[str], label: str, q: Optional[Quantity], kind: Kind, currency: Optional[str],
           required: bool = True) -> bool:
    if q is None:
        if required:
            errors.append(f"{label}: missing")
        return False
    if q.kind != kind:
        errors.append(f"{label}: is {q.kind.value}, expected {kind.value}")
        return False
    if q.kind in (Kind.MONEY, Kind.PER_SHARE, Kind.MONEY_PER_PHYSICAL) and q.currency != currency:
        errors.append(f"{label}: currency {q.currency}, case currency is {currency}; no conversion is performed")
        return False
    if q.kind in (Kind.PHYSICAL, Kind.MONEY_PER_PHYSICAL) and not q.physical_unit:
        errors.append(f"{label}: physical unit missing")
        return False
    if q.status == InputStatus.OBSERVED and not q.evidence_ids:
        errors.append(f"{label}: OBSERVED input has no evidence reference")
    return True


def validate(inputs: BridgeInputs) -> list[str]:
    e: list[str] = []
    cur = inputs.current_price.currency if inputs.current_price else None
    if not cur:
        e.append("current_price: currency missing")
    for label, kind in (("baseline_attributable_profit", Kind.MONEY), ("depreciation", Kind.MONEY),
                        ("interest", Kind.MONEY), ("corporate_costs", Kind.MONEY), ("tax_rate", Kind.PERCENT),
                        ("minority_share", Kind.PERCENT), ("basic_shares", Kind.SHARES),
                        ("working_capital", Kind.MONEY), ("capex", Kind.MONEY), ("debt_service", Kind.MONEY),
                        ("available_funding", Kind.MONEY), ("pe_low", Kind.MULTIPLE), ("pe_high", Kind.MULTIPLE),
                        ("downside_compression", Kind.PERCENT), ("current_price", Kind.PER_SHARE)):
        _check(e, label, getattr(inputs, label), kind, cur)
    _check(e, "current_pe", inputs.current_pe, Kind.MULTIPLE, cur, required=False)

    if not inputs.streams:
        e.append("streams: at least one incremental stream is required")
    if len(inputs.streams) > 3:
        e.append(f"streams: {len(inputs.streams)} given, at most three are allowed")
    names = [s.name for s in inputs.streams]
    if len(set(names)) != len(names):
        e.append("streams: duplicate stream names")
    for s in inputs.streams:
        p = f"stream {s.name!r}"
        for other in s.overlaps_with:
            if other in names:
                e.append(f"{p}: overlaps with stream {other!r}; merge them or remove the overlap")
        if s.kind == "VOLUME":
            ok_v = _check(e, f"{p}.volume", s.volume, Kind.PHYSICAL, cur)
            ok_r = _check(e, f"{p}.realisation", s.realisation, Kind.MONEY_PER_PHYSICAL, cur)
            if ok_v and ok_r and s.volume.physical_unit != s.realisation.physical_unit:
                e.append(f"{p}: realisation is per {s.realisation.physical_unit}, volume is in "
                         f"{s.volume.physical_unit}")
            _check(e, f"{p}.ebitda_margin", s.ebitda_margin, Kind.PERCENT, cur)
        elif s.kind == "CONTRACT":
            _check(e, f"{p}.contract_revenue", s.contract_revenue, Kind.MONEY, cur)
            _check(e, f"{p}.ebitda_margin", s.ebitda_margin, Kind.PERCENT, cur)
        elif s.kind == "MARGIN_RECOVERY":
            _check(e, f"{p}.comparable_revenue", s.comparable_revenue, Kind.MONEY, cur)
            _check(e, f"{p}.incremental_margin", s.incremental_margin, Kind.PERCENT, cur)
            if s.ebitda_margin is not None:
                e.append(f"{p}: margin recovery uses incremental_margin, not ebitda_margin")
        else:
            e.append(f"{p}: unknown kind {s.kind!r}")
        _check(e, f"{p}.ramp_costs", s.ramp_costs, Kind.MONEY, cur, required=False)
        _check(e, f"{p}.cannibalisation", s.cannibalisation, Kind.MONEY, cur, required=False)
    for d in inputs.dilution:
        _check(e, f"dilution {d.name!r}.shares", d.shares, Kind.SHARES, cur)
        _check(e, f"dilution {d.name!r}.cash_in", d.cash_in, Kind.MONEY, cur, required=False)

    if not e:
        if not (Decimal(0) <= inputs.tax_rate.value < 100):
            e.append("tax_rate: must be in [0, 100)")
        if not (Decimal(0) <= inputs.minority_share.value <= 100):
            e.append("minority_share: must be in [0, 100]")
        if inputs.pe_low.value <= 0 or inputs.pe_high.value < inputs.pe_low.value:
            e.append("pe range: need 0 < pe_low <= pe_high")
        if not (Decimal(0) <= inputs.downside_compression.value < 100):
            e.append("downside_compression: must be in [0, 100)")
        if inputs.basic_shares.value <= 0:
            e.append("basic_shares: must be positive")
        if inputs.current_price.value <= 0:
            e.append("current_price: must be positive")
    return e


def compute(inputs: BridgeInputs) -> BridgeResult:
    errors = validate(inputs)
    if errors:
        raise BridgeValidationError(errors)
    hundred = Decimal(100)
    zero = Decimal(0)
    flags: list[str] = []
    out = inputs.presentation_scale.factor

    def opt(q: Optional[Quantity]) -> Decimal:
        return q.base() if q is not None else zero

    revenue: dict[str, Decimal] = {}
    ebitda = zero
    for s in inputs.streams:
        if s.kind == "VOLUME":
            rev = s.volume.value * s.realisation.base()
            contrib = rev * s.ebitda_margin.value / hundred
        elif s.kind == "CONTRACT":
            rev = s.contract_revenue.base()
            contrib = rev * s.ebitda_margin.value / hundred
        else:
            rev = zero              # margin recovery adds margin on existing revenue, not new revenue
            contrib = s.comparable_revenue.base() * s.incremental_margin.value / hundred
        contrib -= opt(s.ramp_costs) + opt(s.cannibalisation)
        revenue[s.name] = rev
        ebitda += contrib
        if s.kind == "VOLUME" and s.realisation.status == InputStatus.ANALYST_ASSUMPTION:
            flags.append(f"stream {s.name!r}: selling price is an analyst assumption, not evidenced; "
                         "capacity x assumed price is not an earnings fact")
        elif any(q is not None and q.status == InputStatus.ANALYST_ASSUMPTION
                 for q in (s.volume, s.contract_revenue, s.comparable_revenue, s.incremental_margin,
                           s.ebitda_margin)):
            flags.append(f"stream {s.name!r} rests on analyst assumptions")

    ebitda -= inputs.corporate_costs.base()
    pbt = ebitda - inputs.depreciation.base() - inputs.interest.base()
    tax = max(pbt, zero) * inputs.tax_rate.value / hundred
    pat = pbt - tax
    attributable_incr = pat * (hundred - inputs.minority_share.value) / hundred
    baseline = inputs.baseline_attributable_profit.base()
    attributable = baseline + attributable_incr

    basic = inputs.basic_shares.base()
    shares = basic + sum((d.shares.base() for d in inputs.dilution), zero)
    baseline_eps = baseline / basic
    eps = attributable / shares
    if attributable > baseline and eps <= baseline_eps:
        flags.append("attributable profit rises but dilution leaves EPS flat or lower")

    cash_in = sum((d.cash_in.base() for d in inputs.dilution if d.cash_in), zero)
    cash_required = inputs.working_capital.base() + inputs.capex.base() + inputs.debt_service.base()
    gap = cash_required - inputs.available_funding.base() - cash_in
    if gap > 0:
        flags.append("profitable is not fundable: cash requirements exceed available funding")

    v_low = eps * inputs.pe_low.value
    v_high = eps * inputs.pe_high.value
    v_comp = eps * inputs.pe_low.value * (hundred - inputs.downside_compression.value) / hundred
    price = inputs.current_price.base()
    ret_low = (v_low / price - 1) * hundred
    v_flat = ret_flat = None
    if inputs.current_pe is not None:
        v_flat = eps * inputs.current_pe.value
        ret_flat = (v_flat / price - 1) * hundred
        if ret_flat <= 0 < ret_low:
            flags.append("expected return depends on multiple expansion")
    else:
        flags.append("no sourced current multiple: no-rerating check not run")
    if eps <= 0:
        flags.append("EPS is not positive: P/E valuation is not meaningful")

    return BridgeResult(
        engine_version=ENGINE_VERSION, inputs_hash=_hash(inputs), period=inputs.period,
        scenario=inputs.scenario.value, currency=inputs.current_price.currency,
        presentation_scale=inputs.presentation_scale.value,
        incremental_revenue={k: _q(v / out) for k, v in revenue.items()},
        incremental_ebitda=_q(ebitda / out), incremental_pbt=_q(pbt / out), incremental_pat=_q(pat / out),
        incremental_attributable=_q(attributable_incr / out), baseline_attributable=_q(baseline / out),
        attributable_profit=_q(attributable / out),
        basic_shares=_q(basic / out, "0.0001"), diluted_shares=_q(shares / out, "0.0001"),
        baseline_eps=_q(baseline_eps), eps=_q(eps),
        value_low=_q(v_low), value_high=_q(v_high), value_compressed=_q(v_comp),
        value_no_rerating=_q(v_flat) if v_flat is not None else None,
        return_at_low_pct=_q(ret_low, "0.1"),
        return_no_rerating_pct=_q(ret_flat, "0.1") if ret_flat is not None else None,
        cash_required=_q(cash_required / out), funding_gap=_q(gap / out), flags=flags,
    )
