"""Figures read from the text of a results filing (pure)."""
from datetime import date
from decimal import Decimal

from inflection.results_text import read_document, read_page

QUARTER = """TECHNOFAB ENGINEERING LIMITED
UNAUDITED STANDALONE FINANCIAL RESULTS FOR THE QUARTER ENDED 30TH JUNE 2020
(Rs. in Lakhs)
STANDALONE
Particulars Quarter Ended Year Ended Quarter Ended Year Ended
30.06.2020 | 31.03.2020 | 30.06.2019 | 31.03.2020
| Revenue from operations 155.10 501.37 1,470.53 5,653.95
il Other income 74.16 238.20 20.71 535.96
i Total Revenue (I+II) 229.26 739.57 1,491.24 6,189.91
(e) Finance costs 668.44 1,191.90 902.22 3,314.29
(f) Depreciation and amortization expense 84.40 35.75 216.80 677.79
Total Expenses (IV) 3,670.73 4,221.13 5,060.65 15,816.32
V Profit (Loss) before exceptional items and tax (Ill -IV) (3,441.47) (3,481.56) (3,569.41) (9,626.41)
Net Profit/(Loss) for the period (5,666.21) (9,692.55) (6,401.61) (22,594.55)
"""

SME_HALF_YEAR = """Statement of Standalone Unaudited Financial Results for the Half Year ended on 30th September, 2024
(Rs. in lakhs)
Standalone
Particulars SiQx Muaorntetrh sE Endnedded Half Year Ended Year Ended
30/09/2024 31/03/2024 30/09/2023 31/03/2024
I Revenue from Operations 2,354.57 2,094.68 2,174.56 4,269.24
II Other Income 44.54 68.27 14.79 83.06
III Total Income 2,399.11 2,162.95 2,189.35 4,352.30
"""


def test_quarter_statement_first_column_in_lakhs_with_negative_profit():
    figs = {f.metric: f for f in read_page(2, QUARTER)}
    rev = figs["revenue"]
    assert (rev.period_type, rev.period_end, rev.scope) == ("QUARTER", date(2020, 6, 30), "STANDALONE")
    assert rev.value == Decimal("155.10") * 10 ** 5 and rev.period_start == date(2020, 4, 1)
    assert figs["pat"].value == Decimal("-5666.21") * 10 ** 5
    assert figs["total_expenses"].value == Decimal("3670.73") * 10 ** 5    # 229.26 - 3,670.73 = -3,441.47 checks


def test_garbled_labels_are_settled_by_the_column_dates():
    (rev,) = [f for f in read_page(1, SME_HALF_YEAR) if f.metric == "revenue"]
    assert rev.period_type == "HALF_YEAR" and rev.period_end == date(2024, 9, 30) and rev.period_start == date(2024, 4, 1)


def test_a_statement_that_does_not_add_up_is_not_read():
    broken = SME_HALF_YEAR.replace("III Total Income 2,399.11", "III Total Income 9,399.11")
    assert read_page(1, broken) == []


def test_no_unit_or_no_scope_label_means_nothing_is_guessed():
    assert read_page(1, SME_HALF_YEAR.replace("(Rs. in lakhs)", "")) == []
    assert read_page(1, SME_HALF_YEAR.replace("Standalone\n", "").replace("Standalone ", "")) == []


def test_expenses_kept_only_when_profit_before_exceptional_items_checks():
    bad = QUARTER.replace("(3,441.47) (3,481.56)", "(3,000.00) (3,481.56)")
    metrics = {f.metric for f in read_page(2, bad)}
    assert "revenue" in metrics and "total_expenses" not in metrics and "finance_cost" not in metrics


def test_ocr_split_decimals_are_not_read():
    split = SME_HALF_YEAR.replace("2,354.57 2,094.68 2,174.56 4,269.24", "2 354 57 2 094 68 2 174 56 4 269 24")
    assert not [f for f in read_page(1, split) if f.metric == "revenue"]


def test_first_statement_per_scope_only():
    assert len([f for f in read_document([(1, SME_HALF_YEAR), (2, SME_HALF_YEAR)]) if f.metric == "revenue"]) == 1


def test_calendar_year_company_nine_months_ending_september():
    text = """Castrol India Limited Unaudited Financial Results for the Quarter and Nine Months ended 30 September 2021
(Rupees in Crore)
Standalone
Particulars Nine Months Nine Months Quarter Quarter Quarter Year
Ended Ended Ended Ended Ended Ended
30.09.21 30.09.20 30.09.21 30.09.20 30.06.21 31.12.20
Revenue from operations 3,067.20 2,079.80 1,123.40 954.00 1,032.70 2,996.80
Other income 31.90 51.20 10.10 14.30 10.50 66.20
Total income 3,099.10 2,131.00 1,133.50 968.30 1,043.20 3,063.00
"""
    (rev,) = [f for f in read_page(2, text) if f.metric == "revenue"]
    assert (rev.period_type, rev.period_start, rev.period_end) == ("NINE_MONTHS", date(2021, 1, 1), date(2021, 9, 30))


def test_ocr_text_without_column_dates_uses_the_statement_title_period():
    text = """AUDITED CONSOLIDATED FINANCIAL RESULTS FOR THE QUARTER AND NINE MONTHS ENDED DECEMBER 31, 2020
Rs in million, except per share data
Consolidated
Particulars
al "neal oceal "ocel "ool a
31, 2020. 30, 2020 31, 2019) 31, 2020) 31, 2019
Revenue from operations. 20,237 19,260 19,653 58,585 57,138 77,643
Other income, net 616 245 348 1,128 765 756
Total income 20,853 19,505 20,001 59,713 57,903 78,399
"""
    (rev,) = [f for f in read_page(3, text) if f.metric == "revenue"]
    assert (rev.period_type, rev.period_end, rev.scope) == ("QUARTER", date(2020, 12, 31), "CONSOLIDATED")
    assert rev.value == 20237 * 10 ** 6
