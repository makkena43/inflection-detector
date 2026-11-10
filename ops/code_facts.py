"""Code triage v1 (replaces Haiku, 10 Nov 2026). Code-only facts for order_check candidate events: the same fields Haiku answers, from fixed text rules.

answer(packet) -> {"events": [{event_id, real_order, kind, amount_cr, amount_foreign, currency, firm, related_party, one_off}]}
The rules are fixed text patterns; they are tuned only for agreement with saved Haiku facts (2025-26), never on returns.
"""
import os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import order_check as oc  # noqa: E402
from order_check import engine  # noqa: E402

I = re.I
PERIOD = re.compile(r"during the (quarter|year|period|month|half)|\bin (q[1-4]|h[12])\b|\b(q[1-4]|h[12]) ?(fy)?\d{2}|year[- ]to[- ]date|\bytd\b|so far (this|in)|"
                    r"aggregat|cumulative|order (book|inflow|backlog|pipeline)|\bbacklog\b|total (order|orders)|orders? (worth|of|aggregating)[^.]{0,60}(during|in) the|"
                    r"(fy|financial year) ?\d{2}[^.]{0,40}(orders|order inflow)|till date|to date|executable|unexecuted|in hand", I)
BID = re.compile(r"\bl-?1\b|lowest bidder|lowest bid|emerged as|declared (the )?(successful|lowest)|bid(s|der)? (submitted|for)|tender (submitted|participat)|qualified (for|in) the bid", I)
SOFT = re.compile(r"letter of intent|\bloi\b|\bmou\b|memorandum of understanding|framework agreement|term sheet|non-binding|expression of interest|intent to award", I)
AWARD = re.compile(r"\b(received|receipt of|bagged|secured|awarded|award of|bags|wins?|won|letter of award|\bloa\b|work order|purchase order|\bpo\b|notification of award|"
                   r"letter of acceptance|signed (a |an )?(contract|agreement)|entered into (a |an )?(contract|agreement)|contract (for|from|with)|order (for|from|worth|valued|of))", I)
OWN = re.compile(r"commercial (production|operation)|commenced production|capacity (addition|expansion)|commissioned (its|our|the company's)|capex|"
                 r"new (plant|facility|unit)|expansion (project|plan)|trial production|commercial operations? date|\bcod\b", I)
CUSTOMER_DONE = re.compile(r"commissioned (for|at|the) [^.]{0,40}(project|plant|substation|line)", I)
RELATED_NO = re.compile(r"(not|no) (a )?(related part|promoter|group compan)|does not (belong|fall)|not related|(promoter|promoter group)[^.]{0,30}(has|have) no interest|arm'?s length", I)
RELATED_YES = re.compile(r"related party|group compan|promoter group (company|entity)|subsidiary of (the|our) (company|promoter)|associate (company|concern)", I)
USD = re.compile(r"(usd|us\$|\$)\s*([\d,.]+)\s*(million|mn|billion|bn)", I)
EUR = re.compile(r"(eur|€)\s*([\d,.]+)\s*(million|mn|billion|bn)", I)


PERIOD2 = re.compile(r"(first|second) half|(last|this|previous|current|the) (quarter|month)|two quarters|order intake|for the (financial )?year|"
                     r"\bfy ?'?\d{2}\b|already received orders|orders? received (so far|till)|new orders worth|in new orders|historical|earlier phase", I)
PLACED = re.compile(r"(company|we) (has |have )?(awarded|placed|issued) (an |the |a )?(order|contract|purchase order)", I)
FILING = ("award", "order")
TALK = ("transcript", "call", "presentation", "annual report", "result")


def doc(title):
    t = (title or "").lower()
    for k in ("transcript", "call", "presentation", "annual report", "press release", "media", "award", "order", "result"):
        if k in t: return k
    return "other"


def facts(e, passages):
    quotes = [(t.get("quote") or "")[:1500] for t in passages]
    t = " ".join(quotes)
    docs = {doc(x.get("title")) for x in passages}
    src = "filing" if docs & set(FILING) else ("talk" if docs and docs <= set(TALK) else "news")
    stage, basis = str(e.get("stage")), str(e.get("amount_basis"))
    amt = engine.crore(e.get("amount"))
    period = bool(PERIOD.search(t)) and not (src == "filing" and not re.search(r"order (book|backlog)|during the (quarter|year)", t, I))
    period = period or (src != "filing" and bool(PERIOD2.search(t)))
    award = bool(AWARD.search(t)) or src == "filing"
    kind, real, firm = "OTHER", False, False
    if PLACED.search(t) or (OWN.search(t) and not AWARD.search(t) and not CUSTOMER_DONE.search(t)) or stage == "FUNDED_PLAN":
        kind = "OWN_CAPEX"
    elif period:
        kind = "ORDER_BOOK" if re.search(r"order (book|backlog)|\bbacklog\b|in hand|unexecuted|executable", t, I) else "PERIOD_TOTAL"
    elif stage in ("AMBITION", "COMMERCIAL_SHIPMENT", "CANCELLED") or re.search(r"\bmou\b|memorandum of understanding|framework agreement|term sheet|expression of interest", t, I):
        kind = "PIPELINE" if stage == "AMBITION" else "OTHER"
    elif BID.search(t) and not re.search(r"letter of award|\bloa\b|work order|purchase order", t, I):
        kind = "BID_OR_L1"
    elif award and (src == "filing" or stage in ("BINDING_DEMAND", "QUALIFIED", "UNKNOWN")) and not (src == "talk" and (stage != "BINDING_DEMAND" or basis != "FIRM")):
        kind, real = "ORDER", True
        firm = not SOFT.search(t) and stage != "QUALIFIED" and basis != "NON_BINDING"
    rel = False if (str(e.get("relationship")) == "ISSUER_ASSERTED_UNRELATED" or RELATED_NO.search(t)) else (True if RELATED_YES.search(t) else None)
    foreign = cur = None
    m = USD.search(t) or EUR.search(t)
    if m and not re.search(r"(rs\.?|inr|₹|rupees)\s*[\d,.]+\s*(crore|cr|lakh)", t, I):
        v = float(m[2].replace(",", "")) * (1000 if m[3].lower() in ("billion", "bn") else 1)
        foreign, cur, amt = v, ("USD" if USD.search(t) else "EUR"), None
    return dict(event_id=e["event_id"], real_order=real, kind=kind, amount_cr=amt if real or kind in ("PERIOD_TOTAL", "ORDER_BOOK") else None,
                amount_foreign=foreign if real else None, currency=cur if real else None, firm=firm if real else False, related_party=rel, one_off=False)


def answer(p):
    passages = p.get("trigger_passages") or []
    return dict(events=[facts(e, [t for t in passages if t.get("event_id") == e.get("event_id")][:oc.MAX_QUOTES]) for e in oc.candidates(p)])
