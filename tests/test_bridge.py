from decimal import Decimal

import pytest

from inflection.bridge import (BridgeInputs, BridgeValidationError, Dilution, Quantity, Stream, compute,
                               validate)
from inflection.states import InputStatus as S, Scenario

O, G, A = S.OBSERVED, S.MANAGEMENT_GUIDANCE, S.ANALYST_ASSUMPTION


def q(v, unit, status=A, ev=()):
    return Quantity.of(v, unit, status, ev)


def base(**over):
    kw = dict(
        period="FY28", scenario=Scenario.BASE,
        baseline_attributable_profit=q(50, "INR_crore", O, ["ev-1"]),
        streams=(Stream("new plant", "VOLUME", ebitda_margin=q(20, "percent"),
                        volume=q(10000, "tonnes", G, ["ev-2"]), realisation=q("0.01", "INR_crore_per_tonnes"),
                        ramp_costs=q(2, "INR_crore")),),
        depreciation=q(3, "INR_crore"), interest=q(1, "INR_crore"), corporate_costs=q(0, "INR_crore"),
        tax_rate=q(25, "percent"), minority_share=q(0, "percent"),
        basic_shares=q(10, "shares_crore", O, ["ev-3"]),
        dilution=(Dilution("warrants", q(1, "shares_crore", O, ["ev-4"]), q(20, "INR_crore", O, ["ev-4"])),),
        working_capital=q(10, "INR_crore"), capex=q(30, "INR_crore"), debt_service=q(5, "INR_crore"),
        available_funding=q(10, "INR_crore"),
        pe_low=q(15, "x"), pe_high=q(25, "x"), downside_compression=q(30, "percent"),
        current_price=q(60, "INR_per_share", O, ["ev-5"]), current_pe=q(12, "x", O, ["ev-6"]),
    )
    kw.update(over)
    return BridgeInputs(**kw)


def test_volume_bridge_arithmetic():
    r = compute(base())
    # revenue 10000 t x 0.01 cr/t = 100 cr; EBITDA 20 - ramp 2 = 18; PBT 18-3-1 = 14; PAT 10.5
    assert r.incremental_revenue == {"new plant": "100.00"}
    assert r.incremental_ebitda == "18.00"
    assert r.incremental_pbt == "14.00"
    assert r.incremental_pat == "10.50"
    assert r.attributable_profit == "60.50"
    assert r.diluted_shares == "11.0000"
    assert r.eps == "5.50"
    assert (r.value_low, r.value_high) == ("82.50", "137.50")
    assert r.value_compressed == "57.75"


def test_funding_gap_is_flagged():
    r = compute(base())
    # needs 45, has 10 + 20 from warrants
    assert r.funding_gap == "15.00"
    assert any("not fundable" in f for f in r.flags)


def test_multiple_expansion_dependence_is_flagged():
    r = compute(base(current_price=q(70, "INR_per_share", O, ["ev-5"])))
    # value at current 12x = 66 < 70, but at 15x = 82.5 > 70
    assert any("multiple expansion" in f for f in r.flags)


def test_dimensional_mismatch_rejected():
    s = Stream("bad", "VOLUME", ebitda_margin=q(20, "percent"), volume=q(5, "MW"),
               realisation=q(1, "INR_crore_per_tonnes"))
    with pytest.raises(BridgeValidationError) as e:
        compute(base(streams=(s,)))
    assert any("INR_crore_per_MW" in m for m in e.value.errors)


def test_overlapping_streams_rejected():
    a = Stream("a", "CONTRACT", ebitda_margin=q(10, "percent"), contract_revenue=q(50, "INR_crore"),
               overlaps_with=("b",))
    b = Stream("b", "CONTRACT", ebitda_margin=q(10, "percent"), contract_revenue=q(50, "INR_crore"))
    assert any("overlaps" in m for m in validate(base(streams=(a, b))))


def test_more_than_three_streams_rejected():
    s = [Stream(f"s{i}", "CONTRACT", ebitda_margin=q(10, "percent"), contract_revenue=q(1, "INR_crore"))
         for i in range(4)]
    assert any("at most three" in m for m in validate(base(streams=tuple(s))))


def test_observed_without_evidence_rejected():
    errs = validate(base(basic_shares=q(10, "shares_crore", O)))
    assert any("OBSERVED input has no evidence" in m for m in errs)


def test_margin_recovery_adds_margin_not_revenue():
    s = Stream("recovery", "MARGIN_RECOVERY", comparable_revenue=q(200, "INR_crore"),
               incremental_margin=q(3, "percent"))
    r = compute(base(streams=(s,)))
    assert r.incremental_revenue == {"recovery": "0.00"}
    assert r.incremental_ebitda == "6.00"


def test_deterministic_hash():
    assert compute(base()).inputs_hash == compute(base()).inputs_hash
    assert compute(base()).inputs_hash != compute(base(period="FY29")).inputs_hash


def test_no_current_multiple_means_no_rerating_check():
    r = compute(base(current_pe=None))
    assert r.value_no_rerating is None
    assert any("no-rerating check not run" in f for f in r.flags)
