"""Shareholding pattern parsing (both XBRL taxonomies), PLI name matching and the 3.5 packet section."""
from decimal import Decimal

from inflection import pli, shareholding
from inflection.packets import contents as C


def _ctx(cid, member):
    return (f'<xbrli:context id="{cid}"><xbrli:entity/><xbrli:scenario><xbrldi:explicitMember dimension="x:CategoryAxis">'
            f'in-bse-shp:{member}</xbrldi:explicitMember></xbrli:scenario></xbrli:context>')


def _fact(tag, cid, v):
    return f'<in-bse-shp:{tag} contextRef="{cid}" unitRef="pure" decimals="INF">{v}</in-bse-shp:{tag}>'


def test_parse_xbrl_2025_fractions():
    xml = "".join([_ctx("T", "ShareholdingPatternMember"), _ctx("M", "MutualFundsOrUTIMember"), _ctx("F", "InstitutionsForeignMember"),
                   _ctx("D", "InstitutionsDomesticMember"), _ctx("P", "ShareholdingOfPromoterAndPromoterGroupMember"),
                   _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "T", "1"),
                   _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "M", "0.0123"),
                   _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "F", "0.1075"),
                   _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "D", "0.4485"),
                   _fact("EncumberedShareUnderPledgedAsPercentageOfTotalNumberOfShares", "P", "0.2456")])
    out = shareholding.parse_xbrl(xml)
    assert out == {"mf_pct": Decimal("1.2300"), "fii_pct": Decimal("10.7500"), "dii_pct": Decimal("44.8500"),
                   "promoter_pledged_pct": Decimal("24.5600")}


def test_parse_xbrl_2020_percentages_and_institutions_total():
    xml = "".join([_ctx("T", "ShareholdingPatternMember"), _ctx("M", "MutualFundsOrUtiMember"),
                   _ctx("F", "InstitutionsForeignPortfolioInvestorMember"), _ctx("I", "InstitutionsMember"),
                   _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "T", "100"),
                   _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "M", "\n0.5\n"),     # a small percent, not a fraction
                   _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "F", "5.7"),
                   _fact("ShareholdingAsAPercentageOfTotalNumberOfShares", "I", "39.89")])
    out = shareholding.parse_xbrl(xml)
    assert out["mf_pct"] == Decimal("0.5") and out["fii_pct"] == Decimal("5.7") and out["dii_pct"] == Decimal("34.19")


def test_parse_master_row():
    r = shareholding.parse_master({"symbol": "KPIL", "date": "30-SEP-2026", "broadcastDate": "16-OCT-2026 16:44:02",
                                   "pr_and_prgrp": "33.58", "public_val": "66.42", "recordId": "214995", "xbrl": "https://x/y.xml"})
    assert r[0] == "KPIL" and str(r[1]) == "2026-09-30" and r[3] == Decimal("33.58") and r[5] == "https://x/y.xml"
    assert r[2].isoformat().startswith("2026-10-16T16:44:02+05:30")


def test_pli_matching_is_strict():
    m = pli.matcher([("a", "Tata Motors Limited"), ("b", "Tata Motors Finance Limited"), ("c", "H.P.COTTON TEXTILE MILLS LTD."),
                     ("d", "Pricol Limited")])
    assert m("Tata Motors Ltd.") == "a"
    assert m("H P Cotton Textile Mills Limited") == "c"
    assert m("Tata") is None                     # one word is never a prefix match
    assert m("Samsung") is None


def test_ownership_section_renders_without_data():
    md = "\n".join(C.ownership_section({}))
    assert "Ownership and other signals" in md and "none public by the cutoff" in md
    md = "\n".join(C.ownership_section({"shareholding": [dict(period_end="2026-09-30", promoter_pct=33.58, promoter_chg_yoy=0.01,
                                                               promoter_pledged_pct=24.56, mf_pct=40.4, mf_chg_yoy=1.2, fii_pct=10.8,
                                                               fii_chg_yoy=-0.1, dii_pct=44.9, retail_pct=8.3)],
                                        "pli": [dict(approval_date="2022-03-24", scheme="PLI ACC", tranche=None,
                                                     committed_investment_cr=None, product_segment=None, source_url="https://pib")],
                                        "signal_filings": [dict(published_at="2026-08-01 10:00 IST", category="capacity addition",
                                                                title="New line", text_artifact_id=None)]}))
    assert "33.58 (0.01)" in md and "PLI ACC" in md and "capacity addition" in md


def test_programme_tsquery_and_order_snippet():
    from inflection import programmes as G
    assert G.tsquery("kavach|train collision avoidance") == "kavach | (train <-> collision <-> avoidance)"
    s, is_order = G.snippet("The company has received an order for Kavach equipment from RDSO.", "kavach|tcas")
    assert is_order and "Kavach" in s
    s, is_order = G.snippet("We see the Kavach opportunity as large over the next decade.", "kavach")
    assert s and not is_order
    assert G.snippet("Nothing here.", "kavach") == (None, False)


def test_ownership_section_lists_programmes():
    md = "\n".join(C.ownership_section({"programmes": [dict(programme="Kavach", announced="2022-02-01", outlay_cr=None,
                                                            first_mention="2022-05-01", first_order_mention="2022-08-01",
                                                            documents=4, order_documents=2, snippet="order for Kavach")]}))
    assert "Kavach (2022-02-01, –)" in md and "4 (2)" in md
