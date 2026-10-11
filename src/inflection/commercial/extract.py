"""Commercial mentions from page text: pure functions, no database.

Every mention keeps the page and the character span of its sentence in that page's stored text,
so it can be cited under the evidence contract (spec section 8) without re-reading the PDF.

Ported from MakroGraph ``earnings_inflection/extraction.py`` and ``chunking.py`` at b31bdd0
(``_split_sentences``, ``is_garbled``, ``_NUMBER_SOUP``, ``_negated_near``, ``classify_modality``,
``order_stage``, ``order_details``, ``_clean_counterparty``, ``relationship_from_text``,
``_fill_order_value``, ``_enrich_single_order_disclosure``).  Changes are listed in
docs/reuse_inventory.md; the main ones:

* sentences carry their page offsets; annexure lines and numbered items are separate sentences;
* amounts keep currency and scale apart (``units.Money``) and plain rupee figures are read too;
* a realised award verb decides the modality of an order sentence, so "has received an order ...
  which will be executed over 18 months" is an observed order, not a forecast;
* a subsidiary named as the *recipient* of an order sets ownership scope, it does not make the
  customer a related party; only the customer side or an explicit annexure answer does;
* regulatory and court orders, order-book totals and safe-harbour text are not customer orders;
* families beyond orders (qualification, commercial start, capacity, loss-drag removal, debt
  reduction, pricing, launches, financing) with stage and observation status per spec 5.2.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from ..units import Money, Scale, parse_amount
from . import vocabulary as V

# ---------------------------------------------------------------- sentences with spans

_BOUNDARY = re.compile(
    r"(?<=[.!?])\s+(?=[A-Z0-9(\"'₹“])"                         # sentence end (ported)
    r"|\n[ \t]*\n\s*"                                          # blank line
    r"|\n(?=[ \t]*(?:\(?\d{1,2}[.)]\s|\(?[a-zA-Z][.)]\s|\(?[ivxIVX]{1,4}[.)]\s|[•●▪◦]|[-–]\s))")  # list item
_ABBREV_END = re.compile(r"(?:\b(?:No|Nos|Rs|Ltd|Pvt|Co|Inc|M/s|Mr|Ms|Dr|viz|approx|Sr|Jr|Re|Mn|Cr|Bn|vs|"
                         r"i\.e|e\.g|etc|Govt|Dept|Corp|Intl|Ref|w\.e\.f)|\b[A-Z])\.$")
_TABLE_NUMBER = re.compile(r"\(?-?\d[\d,]*\.\d+\)?|\(\d[\d,]*\)")
_ENUMERATOR = re.compile(r"\(?(?:\d{1,3}|[a-zA-Z]|[ivxIVX]{1,4})[.)]")
MAX_SENTENCE = 600
SHORT_DOCUMENT_PAGES = 4         # document-level order terms are read only from short announcements


@dataclass(frozen=True)
class Sentence:
    page_no: int
    start: int
    end: int
    text: str                  # whitespace-normalised; the page text at [start, end) normalises to this


def _trimmed(body: str, a: int, b: int) -> Optional[tuple[int, int]]:
    while a < b and body[a].isspace():
        a += 1
    while b > a and body[b - 1].isspace():
        b -= 1
    return (a, b) if b > a else None


def _add(pieces: list[list[int]], body: str, span: tuple[int, int]) -> None:
    """Append a sentence, or join it to the previous piece when that ends in an abbreviation
    ("Rs.", "No.") or is only a list number ("1.", "(a)")."""
    if pieces and "\n\n" not in body[pieces[-1][1]:span[0]]:
        prev = body[pieces[-1][0]:pieces[-1][1]]
        if _ABBREV_END.search(prev) or _ENUMERATOR.fullmatch(prev):
            pieces[-1][1] = span[1]
            return
    pieces.append(list(span))


def split_page(page_no: int, body: str) -> list[Sentence]:
    pieces: list[list[int]] = []
    pos = 0
    for m in _BOUNDARY.finditer(body):
        span = _trimmed(body, pos, m.start())
        if span:
            _add(pieces, body, span)
        pos = m.end()
    span = _trimmed(body, pos, len(body))
    if span:
        _add(pieces, body, span)
    out: list[Sentence] = []
    for a, b in pieces:
        spans = [(a, b)]
        if b - a > MAX_SENTENCE:                        # a table or slide run together: one line each
            spans, line_start = [], a
            for i in range(a, b + 1):
                if i == b or body[i] == "\n":
                    t = _trimmed(body, line_start, i)
                    if t:
                        spans.append(t)
                    line_start = i + 1
        for x, y in spans:
            out.append(Sentence(page_no, x, y, re.sub(r"\s+", " ", body[x:y]).strip()))
    return out


# ---------------------------------------------------------------- text quality (ported)

_WORDLIKE = re.compile(r"^[A-Za-z][a-z]*[aeiouy][a-z]*[.,;:!?)]*$|^[A-Z]{2,6}[.,;:)]*$", re.I)


def is_garbled(text: str) -> bool:
    """PDF text decomposed into letters/fragments ("D c I o T m ! , E w D e b F")."""
    toks = [t for t in text.split() if not re.fullmatch(r"[\d.,%()₹/-]+", t)]
    if len(toks) < 5:
        return False
    singles = sum(1 for t in toks if len(t.strip(".,;:!?()")) <= 1)
    wordlike = sum(1 for t in toks if _WORDLIKE.match(t))
    if singles / len(toks) > 0.35 or wordlike / len(toks) < 0.5:
        return True
    # OCR or glued-text noise ("kEm. tar cftd ... ofUnderstanding ... Powerfrom145MW"): almost no function
    # words and many tokens with case flips, letter-digit joins, stray symbols or no vowel
    if len(toks) >= 10:
        words = [t.strip(".,;:!?()\"'").lower() for t in toks]
        function = sum(w in _FUNCTION_WORDS for w in words) / len(toks)
        junk = sum(1 for t in toks if _JUNK_TOKEN.search(t) or not re.search(r"[aeiouy]", t, re.I)) / len(toks)
        return function < 0.08 and junk > 0.25
    return False


_FUNCTION_WORDS = frozenset("the of and to in a an for is are was were has have had be been by on with from at as "
                            "that this its our we it which will or not".split())
_JUNK_TOKEN = re.compile(r"[a-z][A-Z]|[A-Za-z][0-9]|[0-9][A-Za-z]|[^\w\s.,;:()'\"&/%-]")


def table_row(s: str) -> bool:
    """A statement line ("Repayment of long term borrowings (2,316.72) (1,878.84)"): figures, few words."""
    return len(_TABLE_NUMBER.findall(s)) >= 2 and len(re.findall(r"[A-Za-z]{3,}", s)) <= 10


def number_soup(s: str) -> bool:
    """Slide or table text run together into one 'sentence'."""
    return len(s) > 300 and len(re.findall(r"\d[\d,.]*%?", s)) >= 8


# ---------------------------------------------------------------- modality (ported, plus the realised-verb rule)

def negated_near(s: str, start: int, end: int) -> bool:
    """Negation scopes over a cue only when it sits immediately around it (no clause boundary between)."""
    before = s[max(0, start - 40):start]
    after = s[end:end + 8]
    neg = list(V.NEGATION.finditer(before))
    if neg:
        tail = before[neg[-1].end():]
        if not re.search(r"[,;:]|\b(?:but|while|whereas|although)\b", tail):
            return True
    return bool(re.match(r"\s*(?:not|n't)\b", after))


def classify_modality(s: str) -> str:
    fwd = V.FORWARD.search(s)
    if fwd and negated_near(s, fwd.start(), fwd.end()):
        return "NEGATED"
    if fwd:
        return "CONDITIONAL" if V.CONDITIONAL.search(s) else "FORWARD"
    if V.CONDITIONAL.search(s):
        return "CONDITIONAL"
    return "REALIZED"


def modality_at(s: str, cue: re.Match) -> str:
    """Modality of the passage around ``cue``.  A realised verb inside the cue ("has received",
    "commenced") that is not preceded by a forward word ("expected to be awarded") settles it;
    otherwise the clause around the cue is classified."""
    if negated_near(s, cue.start(), cue.end()):
        return "NEGATED"
    for v in V.REALIZED_VERB.finditer(s, cue.start(), cue.end()):
        if negated_near(s, v.start(), v.end()):
            return "NEGATED"
        if not V.NOT_YET.search(s[max(0, v.start() - 40):v.start()]):
            return "REALIZED"
    left = max([0] + [m.end() for m in re.finditer(r"[;:]|,\s+(?:and|but|which|while)\b", s[:cue.start()])])
    right = re.search(r"[;:]|,\s+(?:and|but|which|while)\b", s[cue.end():])
    clause = s[left:cue.end() + (right.start() if right else len(s))]
    return classify_modality(clause)


# ---------------------------------------------------------------- amounts

_PLAIN_INR = re.compile(r"(?:rs\.?|inr|₹)\s*(\d{1,3}(?:,\d{2,3})+|\d{6,})(?:\.\d+)?\s*(?:/-)?(?!\s*(?:crores?|cr\b|"
                        r"lakhs?|lacs?|mn|million|bn|billion|thousand))", re.I)


def amounts(text: str) -> list[Money]:
    """Every amount in ``text``, in order: scaled amounts via ``units.parse_amount`` and plain
    rupee figures of at least one lakh ("Rs. 4,50,00,000/-") in rupees."""
    found: list[tuple[int, Money]] = []
    pos = 0
    while pos < len(text):
        m = parse_amount(text[pos:])
        if m is None:
            break
        at = text.find(m.original_text, pos)
        found.append((at, m))
        pos = at + len(m.original_text)
    for m in _PLAIN_INR.finditer(text):
        if any(a <= m.start() < a + len(x.original_text) for a, x in found):
            continue
        value = Decimal(m.group(1).replace(",", ""))
        if value >= 100000:
            found.append((m.start(), Money(value, "INR", Scale.UNITS, m.group(0).strip())))
    return [x for _, x in sorted(found, key=lambda t: t[0])]


def _pick_amount(s: str, lifecycle: Optional[str]) -> tuple[Optional[Money], dict]:
    found = amounts(s)
    notes: dict = {}
    if not found:
        return None, notes
    if len(found) > 1:
        notes["amounts_in_sentence"] = len(found)
    if lifecycle == "AMENDED":
        return found[-1], notes                  # "reduced from Rs 450 crore to Rs 300 crore" -> 300
    for m in found:
        before = s[:s.find(m.original_text)][-40:]
        if V.AGGREGATE.search(before):
            notes["aggregate"] = True
            return m, notes
    return found[0], notes


# ---------------------------------------------------------------- dates

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m} | {
    m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_WHEN = re.compile(r"\b(?:by|before|in|during|within|end of|from|on or before|till|until)\s+(?:the\s+)?(?:end\s+of\s+)?"
                   r"(Q[1-4]\s*FY\s*'?\d{2,4}|H[12]\s*FY\s*'?\d{2,4}|FY\s*'?\d{2,4}(?:\s*-\s*\d{2,4})?|"
                   r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)[a-z]*,?\s+\d{4})\b", re.I)


def _fy_year(token: str) -> Optional[int]:
    nums = re.findall(r"\d{2,4}", token)
    if not nums:
        return None
    y = int(nums[-1])
    return y + 2000 if y < 100 else y


def window_end(text: str) -> Optional[date]:
    """Last day of a stated period: Q3FY27 -> 2026-12-31, FY27 -> 2027-03-31, H1FY27 -> 2026-09-30,
    "March 2027" -> 2027-03-31.  Indian fiscal years end on 31 March."""
    t = text.strip()
    q = re.match(r"Q([1-4])\s*FY\s*'?(\d{2,4})", t, re.I)
    if q:
        y = _fy_year(q.group(2))
        return {1: date(y - 1, 6, 30), 2: date(y - 1, 9, 30), 3: date(y - 1, 12, 31), 4: date(y, 3, 31)}[int(q.group(1))]
    h = re.match(r"H([12])\s*FY\s*'?(\d{2,4})", t, re.I)
    if h:
        y = _fy_year(h.group(2))
        return date(y - 1, 9, 30) if h.group(1) == "1" else date(y, 3, 31)
    if re.match(r"FY", t, re.I):
        y = _fy_year(t)
        return date(y, 3, 31) if y else None
    m = re.match(r"([A-Za-z]+),?\s+(\d{4})", t)
    month = m and (_MONTHS.get(m.group(1).lower()) or _MONTHS.get(m.group(1).lower()[:3]))
    if month:
        year = int(m.group(2))
        return date(year, month, calendar.monthrange(year, month)[1])
    return None


def stated_deadline(s: str) -> tuple[Optional[date], str]:
    m = V.DELIVERY.search(s) or _WHEN.search(s)
    if not m:
        return None, ""
    return window_end(m.group(1)), m.group(1)


# ---------------------------------------------------------------- mention

@dataclass
class Mention:
    page_no: int
    span_start: int
    span_end: int
    quote: str
    family: str
    event_type: str
    stage: str                          # CommercialStage value
    lifecycle: Optional[str]            # CANCELLED | EXPIRED | AMENDED | EXECUTED
    modality: str                       # REALIZED | FORWARD | CONDITIONAL | NEGATED
    amount: Optional[Money] = None
    amount_basis: str = "UNQUANTIFIED"
    counterparty: str = ""
    counterparty_named: bool = False
    relationship: str = "UNKNOWN"
    ownership_scope: str = "UNKNOWN"
    details: dict = field(default_factory=dict)

    @property
    def observation_status(self) -> str:
        return "OBSERVED" if self.modality == "REALIZED" else "FORECAST"


def clean_counterparty(raw: str) -> str:
    raw = re.split(r"\.\s+(?!(?:Ltd|Limited|Inc|Corp|Corporation|Pvt|Private|Co|Company|LLP|LLC|PLC)\b)(?=[A-Z][a-z]*(?:\s+[a-z]|$))", raw.strip(), maxsplit=1)[0]   # "L&T. A number" -> "L&T"
    words = raw.strip().split()
    while words and words[0].lower() in {"the", "m/s", "m/s."}:
        words.pop(0)
    while words and words[-1].lower() in {"of", "and", "the"}:
        words.pop()
    name = " ".join(words).strip(" .,")
    if not name or name.split()[0] in V.CAPITALISED_STOPWORDS:
        return ""
    if re.fullmatch(r"(?:Rs|INR|USD|FY\d*|Q\d|Crore|Lakh|Ministry|Hon'?ble)\.?", name.split()[0], re.I):
        return ""
    return name


def _relationship(s: str, verb: Optional[re.Match], cp: Optional[re.Match]) -> tuple[str, str]:
    """(relationship, ownership scope) from one sentence."""
    scope = "UNKNOWN"
    sub = V.SUBSIDIARY_RECIPIENT.search(s)
    if sub and verb and sub.start() < verb.start() and (cp is None or sub.start() < cp.start()):
        scope = "SUBSIDIARY"                 # the subsidiary received the order
        rest = s[verb.start():]
        if V.RELATED.search(rest):
            return "CONFIRMED_RELATED", scope
    elif V.JOINT_VENTURE_RECIPIENT.search(s):
        scope = "JOINT_VENTURE"
    elif V.RELATED.search(s):
        return "CONFIRMED_RELATED", scope
    if V.ASSERT_RELATED.search(s):
        return "CONFIRMED_RELATED", scope
    if V.ASSERT_UNRELATED.search(s):
        return "ISSUER_ASSERTED_UNRELATED", scope
    return "UNKNOWN", scope


def _counterparty(s: str) -> tuple[str, bool, Optional[re.Match], str]:
    for m in V.COUNTERPARTY_NAMED.finditer(s):
        name = clean_counterparty(m.group(1))
        if name:
            return name, True, m, ""
    mu = V.COUNTERPARTY_UNNAMED.search(s)
    return "", False, None, (mu.group(0) if mu else "")


def _order_stage(s: str) -> tuple[str, Optional[str], str]:
    """(stage, lifecycle, wording).  Lifecycle changes first; then the weakest commitment wording
    present wins: unclear wording is never upgraded to binding (ported order)."""
    if V.CANCEL.search(s):
        return "CANCELLED", "CANCELLED", "cancellation"
    if V.EXPIRE.search(s):
        return "CANCELLED", "EXPIRED", "expiry"
    if V.AMEND.search(s):
        return "UNKNOWN", "AMENDED", "amendment"
    if V.RELEASE.search(s):
        return "BINDING_DEMAND", None, "release order"
    if V.INQUIRY.search(s):
        return "AMBITION", None, "inquiry"
    if V.MOU.search(s):
        return "AMBITION", None, "MoU"
    if V.FRAMEWORK.search(s):
        return "QUALIFIED", None, "framework / rate contract"
    if V.PROVISIONAL.search(s):
        return "QUALIFIED", None, "L1 / letter of intent"
    if V.BINDING.search(s):
        return "BINDING_DEMAND", None, "binding order"
    m = V.EXECUTED.search(s)
    if m and not V.NOT_YET.search(s[max(0, m.start() - 40):m.start()]):
        return "COMMERCIAL_SHIPMENT", "EXECUTED", "execution"
    return "UNKNOWN", None, "unclear"


def _order_terms(s: str) -> dict:
    d: dict = {}
    d["tax_basis"] = ("INCLUSIVE" if V.TAX_INCL.search(s) else "EXCLUSIVE" if V.TAX_EXCL.search(s) else "UNKNOWN")
    m = V.DURATION.search(s) or V.DURATION_COLON.search(s)
    if m:
        n = int(m.group(1))
        d["duration_months"] = n * 12 if m.group(2).lower().startswith("year") else n
    for key, pat in (("payment_terms", V.PAYMENT), ("termination_terms", V.TERMINATION)):
        m = pat.search(s)
        if m:
            d[key] = m.group(0)[:120]
    m = V.REFERENCE.search(s)
    if m:
        d["reference_id"] = m.group(1).rstrip(".").upper()
    m = V.PRODUCT.search(s)
    if m:
        d["product"] = m.group(1).strip().lower()
    if V.DISTINCT.search(s):
        d["distinct_marker"] = True
    if V.REPEAT.search(s):
        d["repeat_marker"] = True
    if V.FIRST_ORDER.search(s):
        d["first_order"] = True                   # a customer's first order: a new relationship
    return d


def _order_basis(s: str, amount: Optional[Money], stage: str, wording: str) -> tuple[str, str]:
    if amount is None:
        return "UNQUANTIFIED", ""
    if wording in ("MoU", "inquiry", "L1 / letter of intent"):
        return "NON_BINDING", wording
    if V.MINIMUM.search(s):
        return "GUARANTEED_MINIMUM", ""
    if V.RELEASE.search(s):
        return "EXECUTABLE_RELEASE", ""
    if V.CEILING.search(s) or wording == "framework / rate contract":
        return "CEILING", "up to / framework value, no minimum stated"
    if stage == "UNKNOWN":
        return "NON_BINDING", "commitment wording unclear"
    return "FIRM", ""


def _place(s: str) -> dict:
    d: dict = {}
    fac = V.FACILITY.search(s) or V.FACILITY_BARE.search(s) or V.FACILITY_AT.search(s)
    if fac:
        d["facility"] = re.sub(r"\s+", " ", fac.group(1)).strip().lower()
    seg = V.SEGMENT.search(s)
    if seg:
        d["segment"] = seg.group(1).strip().lower()
    return d


def _family(s: str) -> Optional[tuple[str, str, re.Match]]:
    for name, cue, etype in V.FAMILIES:
        m = cue.search(V.ORDER_NOISE.sub(lambda x: " " * len(x.group(0)), s) if name == "ORDER" else s)
        if not m:
            continue
        if name == "ORDER":
            if V.LEGAL_ORDER.search(s) or V.MARKET_ORDER.search(s):
                continue                         # a court / tax / regulator order
            if (V.ORDER_BOOK.search(s) and not V.AWARD_VERB.search(s)) or V.PERIOD_INFLOW.search(s):
                continue                         # order-book or inflow totals, not one order
            if V.MOU.search(s) and not V.ORDER_NOUN.search(s) and V.MOU_INVESTMENT.search(s):
                return "CAPACITY", "CAPACITY", m  # an investment MoU is a capacity ambition
        if V.ACCOUNTING_NOISE.search(s) or V.BIO_NOISE.search(s) or (name != "FINANCING" and V.HISTORY_NOISE.search(s)):
            return None                          # accounting-policy, ESOP, form or biography text
        if name == "ORDER" and (V.ORDER_LEGAL_NOISE.search(s) or (V.MOU.search(s) and V.JV_FORMATION.search(s))):
            continue                             # litigation, asset lists, JV formation
        if name == "ORDER" and V.MOU.search(s) and not V.ORDER_NOUN.search(s) and V.MOU_NOISE.search(s):
            continue                             # property / payment-term MoUs
        if name == "COMMERCIAL_START" and V.START_NOISE.search(s):
            continue                             # a delayed start has not happened
        if name == "QUALIFICATION" and V.CORPORATE_APPROVAL.search(s) and not re.search(r"vendor|supplier", s, re.I):
            continue                             # approved by the board / members: not a customer approval
        if name == "QUALIFICATION" and V.QUALIFICATION_NOISE.search(s):
            continue                             # accounting text ("EIR method")
        if name == "DEBT_REDUCTION" and V.DEBT_NOISE.search(s):
            continue                             # defaults, cash-flow lines, objects of an issue, servicing
        if name == "PRICING" and V.PRICING_NOISE.search(s):
            continue                             # share price, exchange clarifications, shortages
        if name == "FINANCING" and V.FINANCING_NOISE.search(s):
            continue                             # issue procedure and fund-use statements
        if name == "PRICING" and V.INPUT_COST.search(s) and not V.PASS_THROUGH.search(s):
            continue                             # input prices rising is not the issuer pricing up
        if name == "CAPACITY" and not (amounts(s) or V.CAPACITY_QTY.search(s) or V.FACILITY.search(s)
                                       or V.FACILITY_BARE.search(s) or V.FACILITY_AT.search(s)
                                       or V.CAPACITY_COMMISSIONED.search(s)
                                       or V.CAPACITY_FUNDED.search(s) or V.MOU.search(s)):
            continue                             # capacity talk with no plant, size, money or funding
        return name, etype, m
    return None


def sentence_mention(sent: Sentence) -> Optional[Mention]:
    s = sent.text
    if (len(s) < 12 or is_garbled(s) or V.SAFE_HARBOUR.search(s) or V.ANNEX_FIELD.search(s) or table_row(s)
            or s.rstrip().endswith("?")):
        return None                               # questions (analysts on calls) are not disclosures
    hit = _family(s)
    if hit is None:
        return None
    family, etype, cue = hit
    if family != "ORDER" and number_soup(s):
        return None
    modality = modality_at(s, cue)
    details: dict = {"cue": cue.group(0)[:120]}
    lifecycle: Optional[str] = None
    verb = V.REALIZED_VERB.search(s)
    cp_name, cp_named, cp_match, cp_description = _counterparty(s)
    relationship, scope = _relationship(s, verb, cp_match)
    details |= _place(s)
    deadline, deadline_text = stated_deadline(s)
    if deadline:
        details["deadline"] = deadline.isoformat()
        details["deadline_text"] = deadline_text

    if family == "ORDER":
        stage, lifecycle, wording = _order_stage(s)
        if stage == "UNKNOWN" and lifecycle is None and not amounts(s):
            return None                          # a term or detail sentence, not an order
        if lifecycle in ("CANCELLED", "EXPIRED", "AMENDED"):
            word = (V.CANCEL if lifecycle == "CANCELLED" else V.EXPIRE if lifecycle == "EXPIRED" else V.AMEND).search(s)
            if modality == "NEGATED" or negated_near(s, word.start(), word.end()):
                return None                      # "has not been cancelled": no state change
        details["wording"] = wording
        details |= _order_terms(s)
        amount, notes = _pick_amount(s, lifecycle)
        details |= notes
        if modality in ("FORWARD", "CONDITIONAL") and lifecycle is None:
            details["stated_stage"] = stage
            stage = "AMBITION"                   # an order that is expected is not demand yet
        basis, why = _order_basis(s, amount, stage, wording)
        if why:
            details["basis_reason"] = why
    else:
        amount, notes = _pick_amount(s, None)
        details |= notes
        realized = modality == "REALIZED"
        if family == "COMMERCIAL_START":
            stage = "COMMERCIAL_SHIPMENT" if realized else "AMBITION"
        elif family == "QUALIFICATION":
            stage = "QUALIFIED" if realized else "AMBITION"
        elif family == "CAPACITY":
            q = V.CAPACITY_QTY.search(s)
            if q:
                details["capacity"] = q.group(0)
            if V.MOU.search(s):
                stage = "AMBITION"
                details["wording"] = "MoU"
            elif V.CAPACITY_COMMISSIONED.search(s) and realized:
                stage = "FUNDED_PLAN"
                details["commissioned"] = True
            elif V.CAPACITY_FUNDED.search(s):
                stage = "FUNDED_PLAN"
                details["funding_cue"] = V.CAPACITY_FUNDED.search(s).group(0)[:80]
            else:
                stage = "AMBITION"
            if not details.get("commissioned"):
                modality = modality if modality != "REALIZED" else "FORWARD"   # a plan is a forecast
        else:
            stage = "UNKNOWN"
        if family == "DEBT_REDUCTION":
            if V.EQUITY_FUNDED.search(s):
                details["funded_by_equity"] = True
            if V.RATING.search(s):
                details["rating_upgrade"] = True
        basis = "FIRM" if amount is not None else "UNQUANTIFIED"
        if amount is not None and family in ("CAPACITY", "FINANCING", "DEBT_REDUCTION"):
            basis = "NON_BINDING" if family == "CAPACITY" else "FIRM"
    if cp_description:
        details["counterparty_description"] = cp_description
    if not cp_named and cp_description:
        cp_name = cp_description
    return Mention(sent.page_no, sent.start, sent.end, s, family, etype, stage, lifecycle, modality,
                   amount, basis, cp_name, cp_named, relationship, scope, details)


# ---------------------------------------------------------------- one document

def _fill_order_value(sentences: list[Sentence], mentions: list[Mention]) -> None:
    """One unquantified award plus exactly one stated order value elsewhere in the document
    ("Broad consideration or size of the order: approximately Rs. 358 Crores"): the value belongs to
    that award.  With several awards or several values nothing is linked (ported)."""
    orders = [m for m in mentions if m.family == "ORDER" and m.modality == "REALIZED"]
    awards = [m for m in orders if m.amount is None and m.stage in ("BINDING_DEMAND", "QUALIFIED")
              and V.AWARD_VERB.search(m.quote)]
    restated = [m for m in orders if m.amount is not None and m.stage == "UNKNOWN" and m.lifecycle is None]
    if not awards or any(m.amount is not None for m in orders if m not in restated):
        return
    values: dict = {}
    for sent in sentences:
        t = sent.text
        if V.ORDER_VALUE_CUE.search(t) and V.ORDER_NOUN.search(t):
            found = [a for a in amounts(t) if a.currency == "INR" and a.value > 0]
            if found:
                values.setdefault(found[0].to_base(), (found[0], sent))
    if len(values) != 1 or len({re.sub(r"\W+", " ", m.quote.lower())[:160] for m in awards}) != 1:
        return
    money, sent = next(iter(values.values()))
    m = awards[0]
    m.amount = money
    up_to = re.search(r"\bup\s*to\b|\bceiling\b|\bmaximum\b", sent.text, re.I)
    m.amount_basis = ("NON_BINDING" if m.details.get("wording") == "L1 / letter of intent"
                      else "CEILING" if up_to else "FIRM")
    m.details["amount_source"] = dict(page_no=sent.page_no, span_start=sent.start, span_end=sent.end,
                                      quote=sent.text)
    for r in restated:                            # "The order is worth Rs 358 crore": the same order's value
        if r.amount.to_base() == money.to_base():
            mentions.remove(r)


def _enrich_single_order(text: str, mentions: list[Mention]) -> None:
    """An order disclosure states the order once and its terms elsewhere (SEBI annexure: "Time period
    by which the order is to be executed: 18 months").  With exactly one quantified order in the
    document, its missing terms come from the rest of the document (ported, plus annexure customer
    name, geography and related-party answer)."""
    orders = [m for m in mentions if m.family == "ORDER" and m.amount is not None and m.lifecycle is None
              and m.modality == "REALIZED"]
    if len({(m.amount.to_base(), m.amount.currency) for m in orders}) != 1:
        return
    flat = re.sub(r"[ \t]+", " ", text)
    one = re.sub(r"\s+", " ", text)
    for m in orders:
        d = m.details
        if "duration_months" not in d:
            hit = (re.search(r"\b(?:execut|deliver|complet|suppl)\w*\b[^.]{0,60}?" + V.DURATION.pattern[2:], one, re.I)
                   or V.DURATION_COLON.search(one))
            if hit:
                n = int(hit.group(1))
                d["duration_months"] = n * 12 if hit.group(2).lower().startswith("year") else n
                d["duration_from_document"] = True
        for key, pat in (("payment_terms", V.PAYMENT), ("termination_terms", V.TERMINATION)):
            if key not in d:
                hit = pat.search(one)
                if hit:
                    d[key] = hit.group(0)[:120]
        if "reference_id" not in d:
            hit = V.REFERENCE.search(one)
            if hit:
                d["reference_id"] = hit.group(1).rstrip(".").upper()
        if d.get("tax_basis", "UNKNOWN") == "UNKNOWN":
            d["tax_basis"] = ("INCLUSIVE" if V.TAX_INCL.search(one) else
                              "EXCLUSIVE" if V.TAX_EXCL.search(one) else "UNKNOWN")
        if not m.counterparty_named:
            hit = V.ANNEX_ENTITY.search(flat)
            if hit:
                name = clean_counterparty(re.split(r"\s{2,}|\s+\d+[.)]\s", hit.group(1))[0])
                if name and not re.fullmatch(r"(?:n\.?a\.?|not applicable|confidential|undisclosed)", name, re.I):
                    m.counterparty, m.counterparty_named = name, True
                    d["counterparty_from_annexure"] = True
        hit = V.ANNEX_GEOGRAPHY.search(flat)
        if hit:
            d["customer_geography"] = hit.group(1).upper()
        if m.relationship == "UNKNOWN":
            if V.ASSERT_RELATED.search(flat):
                m.relationship = "CONFIRMED_RELATED"
                d["relationship_from_document"] = True
            elif V.ASSERT_UNRELATED.search(flat):
                m.relationship = "ISSUER_ASSERTED_UNRELATED"
                d["relationship_from_document"] = True


def extract_document(pages: list[tuple[int, str]]) -> tuple[list[Mention], int]:
    """(mentions, sentences read) for one text artifact given its (page_no, body) pages."""
    sentences = [s for page_no, body in pages for s in split_page(page_no, body)]
    out: list[Mention] = []
    seen: set = set()
    for sent in sentences:
        m = sentence_mention(sent)
        if m is None:
            continue
        key = (m.family, re.sub(r"\W+", " ", m.quote.lower()))
        if key in seen:
            continue                              # repeated header / footer text
        seen.add(key)
        out.append(m)
    if len(pages) <= SHORT_DOCUMENT_PAGES:        # an announcement, not a deck, transcript or annual report
        _fill_order_value(sentences, out)
        _enrich_single_order("\n".join(body for _, body in pages), out)
    return out, len(sentences)
