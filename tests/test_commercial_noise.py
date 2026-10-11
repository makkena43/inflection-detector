"""commercial-2 guards: sentences from 2021 filings that commercial-1 misread, and look-alikes it must keep."""

import pytest

from inflection.commercial.extract import extract_document


def families(text: str) -> list[str]:
    mentions, _ = extract_document([(1, text)])
    return [m.family for m in mentions]


@pytest.mark.parametrize("text", [
    "Gains and losses are recognised in profit or loss when the liabilities are derecognised as well as "
    "through the EIR amortisation process.",
    "Annexure Disclosures of defaults on payment of interest/ repayment of principal amount on loans from banks "
    "/ financial institutions and unlisted debt securities for the quarter ended December 31, 2020.",
    "Sub: Intimation of Date of Payment of Interest and Redemption of Debentures of the Company.",
    "1. With regard to the increase in the Price of the Company’s security, the price fluctuations in the "
    "security is market driven and the company has no comment to offer on the same.",
    "That is one of the reasons for shortage and price increase.",
    "The Company had received the certified copy of the said order on 17 July 2020 and the same had been filed "
    "with the respective Registrar of Companies on 1 August 2020.",
    "The Respondents have admitted receipt of Rs. 3 crore as security deposit, and the terms of the MOU require "
    "the security deposit to be repaid within 60 days.",
    "As the property seems to be viable, a JVC will be formed between MOIL and GMDC with shareholding of 51% and "
    "49% respectively, in terms of the MoU already signed.",
    "During the quarter the Company had allotted 4,00,000 equity shares against warrants after receiving the "
    "balance a mou nt.",
    "It is clarified that the proceeds from the Preferential Issue shall be utilized solely in the manner "
    "approved by the shareholders.",
])
def test_noise_is_not_a_commercial_mention(text):
    assert families(text) == []


@pytest.mark.parametrize("text, family", [
    ("Lupin received approval for 5 ANDAs from the US FDA during the quarter.", "QUALIFICATION"),
    ("The company received an EIR from the US FDA for its Unit-VI facility.", "QUALIFICATION"),
    ("The Company has prepaid term loans of Rs. 250 crore during the quarter.", "DEBT_REDUCTION"),
    ("The Company has taken a price increase of 4% across its portfolio to pass on input costs.", "PRICING"),
    ("The Company has signed an MoU with NTPC for supply of 500 MW solar modules.", "ORDER"),
    ("The Bank raised Rs. 1,435 crore through a QIP during the quarter.", "FINANCING"),
])
def test_genuine_mentions_are_kept(text, family):
    assert families(text) == [family]
