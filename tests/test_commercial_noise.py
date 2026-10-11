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


@pytest.mark.parametrize("text", [
    "M. No: FCS-631 7 Encl: a/a HERITAGE FOODS LIMITED CIN : L1 5209TG1992PLC014332 AN ISO: 22000 CERTIFIED COMPANY.",
    "In our opinion, the company has defaulted in repayment of loans or borrowings to a financial institution.",
    "Sub: Disclosures of details on payment of interest/repayment of principal amount on loans from banks.",
    "a. Repayment of borrowings (32.50)",
    "The Chairman called the Meeting to order as the requisite quorum was present and delivered his speech.",
    "The Securities Contracts (Regulation) Rules, 1957, as amended or modified from time to time.",
    "The Group has assessed that its master service agreement with operators contains a lease, as lessor.",
    "If the Company fails to clear title to the property by September 30, 2020, the Company would rescind or "
    "cancel the MOU.",
    "Further, the commercial operation date (COD) in respect of a few subsidiaries has been delayed due to "
    "various reasons.",
    "In case of preferential issue the listed entity shall disclose the following additional details.",
])
def test_commercial_3_noise(text):
    assert families(text) == []


@pytest.mark.parametrize("text, family", [
    ("The Company has been declared L1 bidder for a Rs. 450 crore NHAI contract.", "ORDER"),
    ("Patratu Project: The Company has started its commercial operation from the Patratu plant.", "COMMERCIAL_START"),
    ("The Company reduced Net Debt by Rs. 1,099 crore in the quarter.", "DEBT_REDUCTION"),
])
def test_commercial_3_keeps(text, family):
    assert families(text) == [family]


@pytest.mark.parametrize("text", [
    "Rental revenue is recognized as and when services are rendered as per the master service agreement.",
    "Contracts (Regulation) Rules, 1957, as amended.",
    "The brief summary of the MOU signed by the Company and the lenders are as follows:",
    "The Group has received legal advice that the order and the reduced damages awarded are supported by evidence.",
    "Bid guarantees are returned either upon receipt of an order or in case our bid is unsuccessful.",
    "Reduction in repo rates has resulted in overall lower average cost of debt.",
    "The proceeds will be used for repayment of outstanding loans, meeting our working capital requirements.",
])
def test_commercial_4_noise(text):
    assert families(text) == []


@pytest.mark.parametrize("text", [
    "The Company had received an order dated 1.1.2021 issued by the Member Secretary, Himachal Pradesh State "
    "Pollution Control Board directing to stop that part of the dyeing process.",
    "Trading in derivatives (Specify type of contract, Futures or Options etc.) Exchange on which the trade was executed",
    "Mr. Mayank Goyal is a Commerce Graduate from HR College and Chartered Accountant by Qualification and has "
    "successfully cleared all three levels of the CFA Program.",
    "Revenue related to fixed price contracts are recognized based on our right to invoice for services performed.",
    "4. To guarantee the payment of money secured by or payable under bonds, debentures, contracts and obligations.",
    "The concession period is 50 years from the commercial operation date.",
    "He is responsible commissioned a huge expansion of vitrified tiles at Gailpur in 2011.",
])
def test_commercial_6_noise(text):
    assert families(text) == []
