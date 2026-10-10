from decimal import Decimal

import pytest

from inflection.bridge import (BridgeInputs, BridgeValidationError, Dilution, Quantity as Q, Stream, compute,
                               validate)
from inflection.states import InputStatus as S, Scenario
from inflection.units import Scale

O, G, A = S.OBSERVED, S.MANAGEMENT_GUIDANCE, S.ANALYST_ASSUMPTION
CR = Scale.CRORE


def cr(v, status=A, ev=()):
    return Q.money(v, "INR", CR, status, ev)


def base(**over):
    kw = dict(
        period="FY28", scenario=Scenario.BASE,
        baseline_attributable_profit=cr(50, O, ["ev-1"]),
        streams=(Stream("new plant", "VOLUME", ebitda_margin=Q.percent(20, A),
                        volume=Q.physical(10000, "tonnes", G, ["ev-2"]),
                        realisation=Q.realisation("0.01", "INR", CR, "tonnes", O, ["ev-7"]),
                        ramp_costs=cr(2)),),
        depreciation=cr(3), interest=cr(1), corporate_costs=cr(0),
        tax_rate=Q.percent(25, A), minority_share=Q.percent(0, A),
        basic_shares=Q.shares(10, CR, O, ["ev-3"]),
        dilution=(Dilution("warrants", Q.shares(1, CR, O, ["ev-4"]), cr(20, O, ["ev-4"])),),
        working_capital=cr(10), capex=cr(30), debt_service=cr(5), available_funding=cr(10),
        pe_low=Q.multiple(15, A), pe_high=Q.multiple(25, A), downside_compression=Q.percent(30, A),
        current_price=Q.per_share(60, "INR", O, ["ev-5"]), current_pe=Q.multiple(12, O, ["ev-6"]),
    )
    kw.update(over)
    return BridgeInputs(**kw)


def test_volume_bridge_arithmetic():
    r = compute(base())
    # revenue 10000 t x 0.01 cr/t = 100 cr; EBITDA 20 - ramp 2 = 18; PBT 18-3-1 = 14; PAT 10.5
    assert (r.currency, r.presentation_scale) == ("INR", "CRORE")
    assert r.incremental_revenue == {"new plant": "100.00"}
    assert r.incremental_ebitda == "18.00"
    assert r.incremental_pbt == "14.00"
    assert r.incremental_pat == "10.50"
    assert r.attributable_profit == "60.50"
    assert r.diluted_shares == "11.0000"
    assert r.eps == "5.50"
    assert (r.value_low, r.value_high) == ("82.50", "137.50")
    assert r.value_compressed == "57.75"


def test_scales_mix_correctly():
    # the same inputs expressed in lakh and million give the same answer
    r = compute(base(depreciation=Q.money(300, "INR", Scale.LAKH, A), interest=Q.money(10, "INR", Scale.MILLION, A)))
    assert r.incremental_pbt == "14.00" and r.eps == "5.50"


def test_mixed_currency_rejected_without_conversion():
    errs = validate(base(capex=Q.money(4, "USD", Scale.MILLION, A)))
    assert any("no conversion is performed" in m for m in errs)


def test_regression_8_more_profit_more_shares_weaker_eps():
    # spec section 15 test 8: PAT rises 21% but a 40% larger share count cuts EPS
    r = compute(base(dilution=(Dilution("QIP", Q.shares(4, CR, A), cr(200)),)))
    assert Decimal(r.attributable_profit) > Decimal(r.baseline_attributable)
    assert Decimal(r.eps) < Decimal(r.baseline_eps)            # 60.5/14 = 4.32 < 50/10 = 5.00
    assert any("dilution leaves EPS flat or lower" in f for f in r.flags)


def test_funding_gap_is_flagged():
    r = compute(base())
    assert r.funding_gap == "15.00"           # needs 45, has 10 + 20 from warrants
    assert any("not fundable" in f for f in r.flags)


def test_multiple_expansion_dependence_is_flagged():
    r = compute(base(current_price=Q.per_share(70, "INR", O, ["ev-5"])))
    assert any("multiple expansion" in f for f in r.flags)     # 12x gives 66 < 70; 15x gives 82.5


def test_physical_unit_mismatch_rejected():
    s = Stream("bad", "VOLUME", ebitda_margin=Q.percent(20, A), volume=Q.physical(5, "MW", A),
               realisation=Q.realisation(1, "INR", CR, "tonnes", A))
    with pytest.raises(BridgeValidationError) as e:
        compute(base(streams=(s,)))
    assert any("realisation is per tonnes, volume is in MW" in m for m in e.value.errors)


def test_regression_9_capacity_times_assumed_price_is_flagged():
    s = Stream("capacity", "VOLUME", ebitda_margin=Q.percent(20, A), volume=Q.physical(50, "MW", G, ["ev"]),
               realisation=Q.realisation(5, "INR", CR, "MW", A))
    assert any("selling price is an analyst assumption" in f for f in compute(base(streams=(s,))).flags)


def test_overlapping_streams_rejected():
    a = Stream("a", "CONTRACT", ebitda_margin=Q.percent(10, A), contract_revenue=cr(50), overlaps_with=("b",))
    b = Stream("b", "CONTRACT", ebitda_margin=Q.percent(10, A), contract_revenue=cr(50))
    assert any("overlaps" in m for m in validate(base(streams=(a, b))))


def test_more_than_three_streams_rejected():
    s = [Stream(f"s{i}", "CONTRACT", ebitda_margin=Q.percent(10, A), contract_revenue=cr(1)) for i in range(4)]
    assert any("at most three" in m for m in validate(base(streams=tuple(s))))


def test_observed_without_evidence_rejected():
    assert any("OBSERVED input has no evidence" in m for m in validate(base(basic_shares=Q.shares(10, CR, O))))


def test_wrong_kind_rejected():
    assert any("expected MONEY" in m for m in validate(base(capex=Q.percent(5, A))))


def test_margin_recovery_adds_margin_not_revenue():
    s = Stream("recovery", "MARGIN_RECOVERY", comparable_revenue=cr(200), incremental_margin=Q.percent(3, A))
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
