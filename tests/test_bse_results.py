"""BSE results snapshot: table parsing, periods, signs, scope and the deadline-based availability."""
from datetime import date
from decimal import Decimal

from inflection.bse_results import available_at, parse_table

Q = ("<thead><tr><td>(in Cr.)</td><td>Jun-26</td><td>Mar-26</td><td>FY 25-26</td></tr></thead><tbody>"
     "<tr><td>Revenue</td><td>227.89</td><td>1,238.99</td><td>782.08</td></tr>"
     "<tr><td>Interest</td><td>-0.50</td><td>-0.51</td><td>-2.22</td></tr>"
     "<tr><td>Net Profit</td><td>25.70</td><td>--</td><td>92.77</td></tr>"
     "<tr><td>EPS</td><td>24.20</td><td>22.53</td><td>87.26</td></tr>"
     "<tr><td></td><td>Standalone</td><td>Consolidated</td><td>--</td></tr></tbody>")
A = ("<tr><td>(in Cr.)</td><td>2026</td><td>2025</td></tr><tr><td>Revenue</td><td>782.08</td><td>611.78</td></tr>")


def test_quarter_table():
    f = {(x["metric"], x["period_end"]): x for x in parse_table(Q, annual=False)}
    r = f[("revenue", date(2026, 6, 30))]
    assert r["period_type"] == "QUARTER" and r["period_start"] == date(2026, 4, 1) and r["value"] == Decimal("2278900000.00")
    assert f[("revenue", date(2026, 3, 31))]["value"] == Decimal("12389900000.00")       # thousands separator
    assert f[("finance_cost", date(2026, 6, 30))]["value"] == Decimal("5000000.00")        # expense sign removed
    assert ("pat", date(2026, 3, 31)) not in f                                            # '--' is no value
    assert f[("eps_basic", date(2026, 6, 30))]["value_kind"] == "PER_SHARE"
    assert f[("revenue", date(2026, 6, 30))]["scope"] == "STANDALONE" and f[("revenue", date(2026, 3, 31))]["scope"] == "CONSOLIDATED"
    assert not any(x["period_end"].year == 2025 and x["period_type"] == "QUARTER" for x in f.values())  # FY column skipped


def test_annual_table_and_availability():
    f = parse_table(A, annual=True)
    assert {(x["period_start"], x["period_end"]) for x in f} == {(date(2025, 4, 1), date(2026, 3, 31)), (date(2024, 4, 1), date(2025, 3, 31))}
    assert available_at("ANNUAL", date(2026, 3, 31)).date() == date(2026, 5, 30)
    assert available_at("QUARTER", date(2026, 6, 30)).date() == date(2026, 8, 14)
    assert available_at("QUARTER", date(2026, 3, 31)).date() == date(2026, 5, 30)
