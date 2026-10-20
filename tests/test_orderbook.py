"""Order book / order inflow extraction from presentation and transcript text."""
from datetime import date

from inflection.orderbook import figures, quarter_end


def test_figures_pick_the_amount_next_to_the_wording():
    body = ("Order inflow for the quarter grew by 97.1% to Rs 1,680.76 cr as compared to Rs 852.82 cr last year.\n"
            "• With a healthy order book of Rs 1,431 Cr and good visibility.\n"
            "Analyst: what will the order book be, INR 15,000 crores?")
    f = figures(body)
    assert f["INFLOW"][0] == 1680.76 and f["BOOK"][0] == 1431.0            # the question is skipped


def test_units_and_largest_per_document():
    f = figures("Order book stood at INR 59,300 million. Defence order book now stands at Rs. 817 crores.")
    assert f["BOOK"][0] == 5930.0
    assert round(figures("Highest ever Order Intake of INR 20,456 million in 2022.")["INFLOW"][0], 2) == 2045.6
    assert figures("Revenue of Rs 500 crore with no mention of orders.") == {}


def test_quarter_reported():
    assert quarter_end(date(2023, 2, 10)) == date(2022, 12, 31)
    assert quarter_end(date(2023, 5, 19)) == date(2023, 3, 31)
    assert quarter_end(date(2023, 11, 9)) == date(2023, 9, 30)
