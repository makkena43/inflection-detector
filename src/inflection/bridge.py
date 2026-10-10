"""Deterministic earnings bridge (spec section 7).

The model proposes inputs and evidence; this module computes the bridge.  It
never fills gaps: a missing or dimensionally wrong input is a validation
error, not a default.  Money is INR crore throughout; shares are crore shares,
so EPS comes out in INR per share.

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
from typing import Optional

from .states import InputStatus, Scenario

ENGINE_VERSION = "bridge-1"

INR_CRORE = "INR_crore"
SHARES_CRORE = "shares_crore"
PERCENT = "percent"
MULTIPLE = "x"
INR_PER_SHARE = "INR_per_share"
# Physical units a volume stream may use; realisation must be INR_crore_per_<unit>.
VOLUME_UNITS = {"units", "tonnes", "MW", "MWh", "kL", "sq_ft"}


class BridgeValidationError(ValueError):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    unit: str
    status: InputStatus
    evidence_ids: tuple[str, ...] = ()

    @staticmethod
    def of(value, unit: str, status: InputStatus, evidence_ids=()) -> "Quantity":
        return Quantity(Decimal(str(value)), unit, InputStatus(status), tuple(evidence_ids))


@dataclass(frozen=True)
class Stream:
    """One prospective incremental earnings stream (at most three per case)."""
    name: str
    kind: str                                   # "VOLUME" | "CONTRACT" | "MARGIN_RECOVERY"
    ebitda_margin: Optional[Quantity] = None    # percent; VOLUME and CONTRACT
    volume: Optional[Quantity] = None           # VOLUME: physical units in the period
    realisation: Optional[Quantity] = None      # VOLUME: INR_crore_per_<volume unit>
    contract_revenue: Optional[Quantity] = None # CONTRACT: revenue executed in this period
    comparable_revenue: Optional[Quantity] = None   # MARGIN_RECOVERY
    incremental_margin: Optional[Quantity] = None   # MARGIN_RECOVERY: percent points
    ramp_costs: Optional[Quantity] = None
    cannibalisation: Optional[Quantity] = None  # EBITDA lost elsewhere in the business
    overlaps_with: tuple[str, ...] = ()         # declared overlap with another stream -> rejected


@dataclass(frozen=True)
class Dilution:
    name: str                                   # e.g. "warrants 2027", "QIP scenario financing"
    shares: Quantity                            # shares_crore, weighted for the period
    cash_in: Optional[Quantity] = None          # INR_crore raised


@dataclass(frozen=True)
class BridgeInputs:
    period: str
    scenario: Scenario
    baseline_attributable_profit: Quantity      # normalised, INR_crore
    streams: tuple[Stream, ...]
    depreciation: Quantity                      # incremental, INR_crore
    interest: Quantity                          # incremental, INR_crore
    corporate_costs: Quantity                   # incremental, INR_crore
    tax_rate: Quantity                          # percent
    minority_share: Quantity                    # percent of incremental profit
    basic_shares: Quantity                      # shares_crore, weighted average
    dilution: tuple[Dilution, ...]
    working_capital: Quantity
    capex: Quantity
    debt_service: Quantity
    available_funding: Quantity                 # cash + committed facilities, INR_crore
    pe_low: Quantity                            # MULTIPLE
    pe_high: Quantity
    downside_compression: Quantity              # percent cut to pe_low for the downside value
    current_price: Quantity                     # INR_per_share
    current_pe: Optional[Quantity] = None       # sourced trailing multiple for the no-rerating check


@dataclass
class BridgeResult:
    engine_version: str
    inputs_hash: str
    period: str
    scenario: str
    incremental_revenue: dict[str, str]
    incremental_ebitda: str
    incremental_pbt: str
    incremental_pat: str
    incremental_attributable: str
    attributable_profit: str
    diluted_shares: str
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
        if hasattr(o, "value"):
            return o.value
        raise TypeError(type(o))
    blob = json.dumps(asdict(inputs), default=default, sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def _check_unit(errors: list[str], label: str, q: Optional[Quantity], unit: str, required: bool = True) -> bool:
    if q is None:
        if required:
            errors.append(f"{label}: missing")
        return False
    if q.unit != unit:
        errors.append(f"{label}: unit {q.unit!r}, expected {unit!r}")
        return False
    if q.status == InputStatus.OBSERVED and not q.evidence_ids:
        errors.append(f"{label}: OBSERVED input has no evidence reference")
    return True


def validate(inputs: BridgeInputs) -> list[str]:
    e: list[str] = []
    for label, unit in (("baseline_attributable_profit", INR_CRORE), ("depreciation", INR_CRORE),
                        ("interest", INR_CRORE), ("corporate_costs", INR_CRORE), ("tax_rate", PERCENT),
                        ("minority_share", PERCENT), ("basic_shares", SHARES_CRORE),
                        ("working_capital", INR_CRORE), ("capex", INR_CRORE), ("debt_service", INR_CRORE),
                        ("available_funding", INR_CRORE), ("pe_low", MULTIPLE), ("pe_high", MULTIPLE),
                        ("downside_compression", PERCENT), ("current_price", INR_PER_SHARE)):
        _check_unit(e, label, getattr(inputs, label), unit)
    _check_unit(e, "current_pe", inputs.current_pe, MULTIPLE, required=False)

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
            if _check_unit(e, f"{p}.volume", s.volume, s.volume.unit if s.volume else ""):
                if s.volume.unit not in VOLUME_UNITS:
                    e.append(f"{p}.volume: unit {s.volume.unit!r} is not a recognised volume unit")
                _check_unit(e, f"{p}.realisation", s.realisation, f"{INR_CRORE}_per_{s.volume.unit}")
            _check_unit(e, f"{p}.ebitda_margin", s.ebitda_margin, PERCENT)
        elif s.kind == "CONTRACT":
            _check_unit(e, f"{p}.contract_revenue", s.contract_revenue, INR_CRORE)
            _check_unit(e, f"{p}.ebitda_margin", s.ebitda_margin, PERCENT)
        elif s.kind == "MARGIN_RECOVERY":
            _check_unit(e, f"{p}.comparable_revenue", s.comparable_revenue, INR_CRORE)
            _check_unit(e, f"{p}.incremental_margin", s.incremental_margin, PERCENT)
            if s.ebitda_margin is not None:
                e.append(f"{p}: margin recovery uses incremental_margin, not ebitda_margin")
        else:
            e.append(f"{p}: unknown kind {s.kind!r}")
        _check_unit(e, f"{p}.ramp_costs", s.ramp_costs, INR_CRORE, required=False)
        _check_unit(e, f"{p}.cannibalisation", s.cannibalisation, INR_CRORE, required=False)
    for d in inputs.dilution:
        _check_unit(e, f"dilution {d.name!r}.shares", d.shares, SHARES_CRORE)
        _check_unit(e, f"dilution {d.name!r}.cash_in", d.cash_in, INR_CRORE, required=False)

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
    return e


def compute(inputs: BridgeInputs) -> BridgeResult:
    errors = validate(inputs)
    if errors:
        raise BridgeValidationError(errors)
    hundred = Decimal(100)
    flags: list[str] = []

    revenue: dict[str, Decimal] = {}
    ebitda = Decimal(0)
    for s in inputs.streams:
        if s.kind == "VOLUME":
            rev = s.volume.value * s.realisation.value
            contrib = rev * s.ebitda_margin.value / hundred
        elif s.kind == "CONTRACT":
            rev = s.contract_revenue.value
            contrib = rev * s.ebitda_margin.value / hundred
        else:
            rev = Decimal(0)        # margin recovery adds margin on existing revenue, not new revenue
            contrib = s.comparable_revenue.value * s.incremental_margin.value / hundred
        contrib -= (s.ramp_costs.value if s.ramp_costs else 0)
        contrib -= (s.cannibalisation.value if s.cannibalisation else 0)
        revenue[s.name] = rev
        ebitda += contrib
        if any(q is not None and q.status == InputStatus.ANALYST_ASSUMPTION
               for q in (s.volume, s.realisation, s.contract_revenue, s.comparable_revenue,
                         s.incremental_margin, s.ebitda_margin)):
            flags.append(f"stream {s.name!r} rests on analyst assumptions")

    ebitda -= inputs.corporate_costs.value
    pbt = ebitda - inputs.depreciation.value - inputs.interest.value
    tax = max(pbt, Decimal(0)) * inputs.tax_rate.value / hundred
    pat = pbt - tax
    attributable_incr = pat * (hundred - inputs.minority_share.value) / hundred
    attributable = inputs.baseline_attributable_profit.value + attributable_incr

    shares = inputs.basic_shares.value + sum((d.shares.value for d in inputs.dilution), Decimal(0))
    eps = attributable / shares

    cash_in = sum((d.cash_in.value for d in inputs.dilution if d.cash_in), Decimal(0))
    cash_required = inputs.working_capital.value + inputs.capex.value + inputs.debt_service.value
    gap = cash_required - inputs.available_funding.value - cash_in
    if gap > 0:
        flags.append("profitable is not fundable: cash requirements exceed available funding")

    v_low = eps * inputs.pe_low.value
    v_high = eps * inputs.pe_high.value
    v_comp = eps * inputs.pe_low.value * (hundred - inputs.downside_compression.value) / hundred
    price = inputs.current_price.value
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
        scenario=inputs.scenario.value,
        incremental_revenue={k: _q(v) for k, v in revenue.items()},
        incremental_ebitda=_q(ebitda), incremental_pbt=_q(pbt), incremental_pat=_q(pat),
        incremental_attributable=_q(attributable_incr), attributable_profit=_q(attributable),
        diluted_shares=_q(shares, "0.0001"), eps=_q(eps),
        value_low=_q(v_low), value_high=_q(v_high), value_compressed=_q(v_comp),
        value_no_rerating=_q(v_flat) if v_flat is not None else None,
        return_at_low_pct=_q(ret_low, "0.1"),
        return_no_rerating_pct=_q(ret_flat, "0.1") if ret_flat is not None else None,
        cash_required=_q(cash_required), funding_gap=_q(gap), flags=flags,
    )
