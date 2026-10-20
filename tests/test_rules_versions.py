"""Triage rules 3.3 and 3.4 are both selectable; 3.4 adds the thin-margin / cheap-valuation exception for routine
orders and a computed valuation-and-margin section in the packet."""
import os
import subprocess
import sys
from decimal import Decimal

from inflection.packets import contents as C
from inflection.packets import rules as R


def test_default_is_34_and_33_is_unchanged_text():
    assert R.TRIAGE_RULES_VERSION == "triage-rules-3.4" and R.RULES is R.RULES_3_4
    assert 'EXCEPT when the packet\'s "Valuation and margin"' in R.RULES_3_4
    assert "Valuation and margin" not in R.RULES_3_3
    assert R.RULES_3_4.replace(R._ROUTINE_34, R._ROUTINE_33).replace(R._DEEP_34, R._DEEP_33) == R.RULES_3_3


def test_switch_back_to_33():
    out = subprocess.run([sys.executable, "-c", "from inflection.packets import rules as R, contents as C;"
                          "print(R.TRIAGE_RULES_VERSION, R.WITH_VALUATION, C.PACKET_VERSION)"],
                         env=dict(os.environ, INFLECTION_TRIAGE_RULES="3.3"), capture_output=True, text=True, check=True)
    assert out.stdout.split() == ["triage-rules-3.3", "False", "triage-packet-2"]


def _q(v):
    return [dict(value=str(x)) for x in v]


def test_valuation_section():
    fin = dict(status="FOUND", rows=dict(revenue=_q([100] * 4 + [125] * 4), pbt=_q([5] * 4 + [10] * 4),
                                         finance_cost=_q([1] * 8), depreciation=_q([2] * 8), other_income=_q([0] * 8)))
    v = C.valuation(fin, dict(market_cap_cr="400"))
    assert v["price_to_sales"] == "0.80" and v["opm_ttm_pct"] == "10.4" and v["opm_change_pts"] == "2.4"
    assert v["revenue_growth_ttm_pct"] == "25.0"
    assert C.valuation(dict(status="MISSING"), {})["status"] == "MISSING"


def test_valuation_tolerates_formatted_or_missing_cells():
    fin = dict(status="FOUND", rows=dict(revenue=_q(["1,000"] * 4), pbt=_q([50] * 4), finance_cost=_q([0] * 4),
                                         depreciation=[dict(value="–")] * 4, other_income=_q([0] * 4)))
    v = C.valuation(fin, dict(market_cap_cr="400"))
    assert v["status"] == "FOUND" and v["opm_ttm_pct"] is None and v["ttm_revenue_cr"] is None
