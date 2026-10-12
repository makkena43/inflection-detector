"""Versioned vocabulary and thresholds for the commercial route (spec 5.1: dictionaries apart from code).

Change anything here and bump ``RULES_VERSION``: mentions, scans and evaluations carry the version
that produced them, and the policy hash stored on every candidate evaluation is computed from this
module's patterns and thresholds.

The order vocabulary (award, commitment-strength, lifecycle and order-term cues) is ported from
MakroGraph ``earnings_inflection/extraction.py`` at b31bdd0 (see docs/reuse_inventory.md).  The other
families are new and follow spec 18.1's list of commercial changes: customer qualification,
commercial shipment / production start, commissioned or funded capacity, input-price retention,
debt-service reduction, removal of a loss-making drag, product launches, and equity financing
(kept as context: it funds plans and dilutes holders, it is not an operating catalyst).
"""

from __future__ import annotations

import hashlib
import re

RULES_VERSION = "commercial-2"

I = re.I

# ---------------------------------------------------------------- modality (ported)

NEGATION = re.compile(
    r"\b(?:not|no(?!\.|\s*[:#\d])|never|neither|nor|unlikely|did not|didn't|do not|don't|does not|doesn't|won't|"
    r"will not|cannot|can't|without|yet to|failed to|none)\b", I)
FORWARD = re.compile(
    r"\b(?:expect(?:s|ed|ing)?|target(?:s|ing)?|guid(?:e|ance|ing)|will|shall|aim(?:s|ing)?|plan(?:s|ned|ning)?|"
    r"anticipat\w*|outlook|envisag\w*|going forward|by FY\s*'?\d{2}|next (?:year|quarter|fiscal)|"
    r"projected|estimate[sd]?|intend\w*|aspir\w*|confident of|should (?:be|reach|grow)|propos\w*|"
    r"likely to|set to|in the process of|upcoming)\b", I)
CONDITIONAL = re.compile(r"\b(?:if|subject to|could|may|might|depending on|assuming|provided that|"
                         r"potential(?:ly)?)\b", I)
# a forward or modal word right before a verb makes it not (yet) realised: "expected to be awarded"
NOT_YET = re.compile(r"\b(?:to|be|will|would|shall|may|might|could|expect\w*|likely|plan\w*|propos\w*|"
                     r"intend\w*|aim\w*|yet to|set to|going to|anticipat\w*)\s+(?:\w+\s+){0,2}$", I)
REALIZED_VERB = re.compile(
    r"\b(?:received|receives|bagged|bags|secured|secures|won|wins|awarded|signed|executed|commenced|started|"
    r"began|begun|commissioned|completed|achieved|launched|introduced|qualified|approved|empanell?ed|"
    r"obtained|granted|cleared|repaid|prepaid|redeemed|retired|divested|sold|closed|exited|hived|"
    r"increased|hiked|revised|passed|dispatched|shipped|delivered|declared|placed|allotted|raised)\b", I)

# ---------------------------------------------------------------- what is not a commercial passage

SAFE_HARBOUR = re.compile(r"forward[- ]looking statements?|safe harbou?r|actual results (?:may|could) differ|"
                          r"undue reliance|no obligation to (?:publicly )?update", I)
# Filing categories / titles with no commercial content (rules still read every other filing,
# including annual reports and board outcomes with generic titles).
SKIP_CATEGORY = re.compile(
    r"trading window|newspaper (?:publication|advertisement)|loss of share certificate|duplicate share certificate|"
    r"share certificates? (?:lost|issued)|regulation 74\s*\(5\)|reg\.? ?74\s*\(5\)|investor complaints|"
    r"compliance certificate|statement of investor|esop|esos|employee stock|record date|book closure|"
    r"postal ballot|scrutini[sz]er|voting results|change in (?:registrar|rta)|cessation|resignation of|"
    r"appointment of (?:company secretary|compliance officer|statutory auditor|secretarial auditor)|"
    r"credit rating\b(?!.*upgrad)|disclosure under sast|regulation 31\(4\)|encumbrance|pledge|"
    r"analyst ?/ ?investor meet(?:ing)? (?:intimation|schedule)|schedule of analyst|"
    r"intimation of (?:analyst|investor) (?:meet|call)", I)
# Pre-filters (rules version commercial-2): passages that are not disclosures at all.  Each one only
# fires when no realised-award wording, amount or achieved-date verb rescues the sentence.
# "Scheduled Commercial Operation Date (SCOD)" / "C.O.D. Commercial Operations Date": a defined term,
# not a commissioning, unless the sentence says it was achieved or declared.
COD_TERM = re.compile(r"\bSCOD\b|\bC\.O\.D\.?|\bcommercial operations? date\b", I)
COD_ACHIEVED = re.compile(r"\b(?:achiev\w*|declar\w*|attain\w*|reach\w*|commenc\w*|commission\w*|started|completed|"
                          r"operationali[sz]\w*|successfully)\b", I)
# Exchange cover letter / header run into one sentence ("Date: ... To BSE Limited The National Stock Exchange ...").
COVER_LETTER = re.compile(r"\bscrip (?:code|id)\b|\bto,? (?:the )?(?:BSE Limited|National Stock Exchange)\b|"
                          r"\bdear sirs?\b|\bthe (?:manager|general manager|listing department)\b.{0,80}"
                          r"(?:exchange|BSE)|^\W*(?:ref|sub|subject)\s*[:.\-]", I)
# Board-meeting intimations: "the Board of Directors, at its meeting held today, approved ..." (results, fund
# raising, record dates).  Not a commercial event on their own.
BOARD_MEETING = re.compile(r"\bboard of directors\b.{0,120}\bmeeting\b.{0,40}\b(?:held|today|on)\b", I)
# Words that make a cover-letter sentence carry real news; the cover-letter rules stand down if any is present.
NEWS_WORD = re.compile(r"\b(?:awards?(?:ed)?|orders?|contracts?|letter of (?:award|intent)|LoA|LoI|L-?1|commission\w*|"
                       r"approvals?|approved by|launch\w*|capacity|plant|facility|commenc\w*|COD|bagged|secured|won|"
                       r"wins?|receiv\w*|empanel\w*|ANDA|USFDA)\b", I)
# SEBI disclosure template rows copied without an answer ("Any advance paid or received for the contract").
TEMPLATE_ROW = re.compile(r"\bany advance paid or received\b|\bmanner of determining the pricing\b|"
                          r"\bwhether the (?:order|contract)s? (?:is|are) (?:from|with)\b|"
                          r"\bindicative time period\b", I)
# Cash-flow / statement rows whose columns are dashes ("Repayment of Loans Given - - - - -").
DASH_COLUMNS = re.compile(r"(?:^|\s)[-\u2013\u2014](?:\s+[-\u2013\u2014]){2,}(?:\s|$)")
YEAR = re.compile(r"\b(20[0-3]\d)\b")
# Letters of intent / awards that the sentence itself dates two or more years before the filing.
STALE_AFTER_YEARS = 2

# Regulatory / legal orders are not customer orders.
_AUTHORITY = (r"(?:NCLT|NCL T|NCLAT|court|tribunal|SEBI|SAT|GST|tax|income[- ]tax|assessments?|demand|penalty|show[- ]cause|"
              r"adjudicat\w*|arbitra\w*|regulator|authority|commissioner|CESTAT|DGGI|enforcement|RBI|"
              r"stock exchanges?|directorate|ministry of corporate affairs|ROC|registrar|Hon'?ble|CCI|Competition Commission|"
              r"CC[Il]|DG|NGT|pollution control board|high court|supreme court|AY\s*\d\d|assessment years?|appeals?|"
              r"rectification)")
_SPAN50 = r"(?:[^.]|\.(?=\d)|(?<=\b[a-zA-Z])\.){0,50}"     # dates (10.05.2023) and "i.e." do not end it
LEGAL_ORDER = re.compile(
    rf"\b{_AUTHORITY}\b{_SPAN50}\border|\borders?\b{_SPAN50}\b(?:{_AUTHORITY[3:-1]}|under section|u/s|passed by|"
    r"imposing|levying|appeal|adjudicating)\b", I)
# "in order to", buy-back / market orders, standing orders: the word "order" without a customer
ORDER_NOISE = re.compile(r"\bin order (?:to|for|that)\b|\bin the order of\b|\b(?:standing|delegation|pecking|"
                         r"chronological|descending|ascending) order\b|\border of (?:the )?(?:board|court|tribunal)\b",
                         I)
MARKET_ORDER = re.compile(r"\b(?:buy-?back|tender offer|open offer|eligible shareholders?|bids? from|stock ?brokers?|"
                          r"trading members?|demat|order book of the exchange|bidding period|custodian|participant)\b", I)
FIRST_ORDER = re.compile(r"\bfirst (?:\w+ ){0,2}(?:order|purchase order|contract)\b|\bnew (?:customer|client)\b", I)
# SEBI order-annexure field lines ("h) Whether the promoter ... awarded the order: No") feed the
# document-level terms; they are not order announcements themselves
ANNEX_FIELD = re.compile(r"^\W*(?:\(?(?:\d{1,2}|[a-zA-Z]|[ivx]{1,4})[.)]\s*)?(?:whether|name of|nature of|broad "
                         r"consideration|size of|significant terms|time period|details of|brief details|quantity|"
                         r"date of)\b", I)
ORDER_BOOK = re.compile(r"\border\s*(?:book|backlog|inflows?|intake|pipeline|position)\b|\bunexecuted orders?\b", I)

# ---------------------------------------------------------------- order family (ported from MakroGraph)

ORDER_CUE = re.compile(
    r"\b(?:received|receives|receipt of|bagged|bags|bagging(?: of)?|secured|secures|won|wins|awarded|has been awarded)"
    r"\b.{0,80}\b(?:orders?|contracts?|letter of (?:award|intent)|LoA|LoI|purchase orders?|work orders?)\b|"
    r"\b(?:orders?|contracts?)\b.{0,40}\b(?:worth|valued at|aggregating|amounting to|of value)\b|"
    r"\bletter of (?:award|intent)\b|(?-i:\bL-?1\b)(?: bidder| position)?|\blowest bidder\b|\bMoU\b|"
    r"\bmemorandum of understanding\b|\bframework agreement\b|\brate contract\b|"
    r"\bmaster (?:supply|service) agreement\b|\brelease orders?\b|"
    r"\b(?:orders?|contracts?|LoA|purchase orders?|work orders?)\b.{0,80}\b(?:cancell?ed|terminated|"
    r"short[- ]closed|amended|revised|reduced|expired|lapsed|executed|delivered|completed)\b|"
    r"\b(?:cancell?ation|termination|amendment|short[- ]closure|cancell?ed|terminated|short[- ]closed)\b.{0,60}"
    r"\b(?:orders?|contracts?|LoA)\b", I)
BINDING = re.compile(r"\b(?:purchase order|work order|contract (?:signed|executed|awarded)|letter of award|LoA|"
                     r"(?:received|receives|bagged|bags|secured|secures|won|wins|booked)\b[^.]{0,60}?\b(?:orders?|"
                     r"contracts?)|bagged|secured|awarded|firm orders?|confirmed (?:\w+ ){0,2}orders?|"
                     r"(?:receipt|bagging) of (?:an? )?(?:orders?|contracts?))\b", I)
PROVISIONAL = re.compile(r"(?-i:\bL-?1\b)|\blowest bidder\b|\bletter of intent\b|\bLoI\b|\bselected as\b|\bshortlisted\b", I)
MOU = re.compile(r"\bMoU\b|\bmemorandum of understanding\b", I)
FRAMEWORK = re.compile(r"\bframework agreement\b|\brate contract\b|\bmaster (?:supply|service) agreement\b", I)
INQUIRY = re.compile(r"\bin (?:advanced )?discussions?\b|\bpipeline\b|\benquir(?:y|ies)\b|\bbids? submitted\b|"
                     r"\bnegotiations?\b", I)
DISTINCT = re.compile(r"\b(?:repeat|fresh|another|additional|second|third|new|follow[- ]on) "
                      r"(?:order|contract|purchase order)\b", I)
REPEAT = re.compile(r"\b(?:repeat|follow[- ]on) (?:orders?|contracts?|purchase orders?)\b", I)
CANCEL = re.compile(r"\b(?:cancell?ed|cancell?ation|terminated|termination of the (?:order|contract)|short[- ]closed|"
                    r"foreclosed|withdrawn by the (?:customer|client))\b", I)
EXPIRE = re.compile(r"\b(?:expired|lapsed)\b", I)
AMEND = re.compile(r"\b(?:amended|amendment|revised (?:order |contract )?value|(?:reduced|increased|revised) to|"
                   r"scope (?:reduced|enhanced|revised))\b", I)
EXECUTED = re.compile(r"\b(?:executed|delivered|commissioned|completed (?:the )?(?:supply|execution|delivery|order))\b", I)

# order terms (ported)
CEILING = re.compile(r"\b(?:up ?to|maximum|ceiling|not exceeding|estimated (?:total )?(?:value|contract value))\b", I)
MINIMUM = re.compile(r"\b(?:minimum (?:guaranteed|offtake|commitment|order)|guaranteed minimum)\b", I)
RELEASE = re.compile(r"\b(?:release|call[- ]off|drawdown) orders?\b", I)
TAX_INCL = re.compile(r"\b(?:inclusive of|including|incl\.?)\s+(?:all\s+)?(?:gst|taxes|tax|duties)\b", I)
TAX_EXCL = re.compile(r"\b(?:exclusive of|excluding|excl\.?|plus)\s+(?:applicable\s+)?(?:gst|taxes|tax)\b|\+\s*gst\b", I)
DURATION = re.compile(r"\b(?:over|within|in|for|spread over)\s+(?:a\s+)?(?:period\s+of\s+)?(\d{1,3})\s*(months?|years?)\b", I)
DURATION_COLON = re.compile(r"\b(?:execut|deliver|complet|suppl)\w*\b[^.]{0,60}?[:\-–]\s*(?:within\s+)?(\d{1,3})\s*"
                            r"(months?|years?)\b", I)
DELIVERY = re.compile(r"\b(?:to be (?:executed|delivered|completed)|delivery|execution|completion)\b[^.;]{0,30}"
                      r"\b(?:by|before|during|in|on or before)\s+((?:Q[1-4]\s*)?FY\s*'?\d{2,4}|[A-Z][a-z]+,?\s+\d{4})", I)
PAYMENT = re.compile(r"\b(?:payment terms?|advance of|milestone payments?|letter of credit|payment (?:within|after))"
                     r"\b[^.;]{0,100}", I)
TERMINATION = re.compile(r"\b(?:termination|terminate|cancellation clause|liquidated damages)\b[^.;]{0,100}", I)
REFERENCE = re.compile(r"\b(?:PO|purchase order|LoA|LOA|letter of award|work order|contract|tender|NIT)\s*"
                       r"(?:no\.?|number|ref\.?|reference)\s*[:#]?\s*([A-Z0-9][A-Z0-9/\-_.]{3,})", I)
PRODUCT = re.compile(r"\bfor (?:the )?(?:supply|manufacture|design|construction|installation|execution|delivery|"
                     r"commissioning|provision|development|procurement|operation and maintenance) of ([^.,;]{3,70})", I)
ORDER_VALUE_CUE = re.compile(r"\b(?:total\s+)?(?:amount|value|size|consideration|worth)\b", I)
ORDER_NOUN = re.compile(r"\b(?:work\s+orders?|orders?|contracts?|LoA|letter\s+of\s+award|supply|award)\b", I)
AWARD_VERB = re.compile(r"\b(?:received|receives|bagged|bags|secured|won|awarded|receipt\s+of|bagging\s+of|bagging)\b"
                        r".{0,120}\b(?:orders?|contracts?|letter\s+of\s+(?:award|intent)|LoA|LoI)\b", I)
AGGREGATE = re.compile(r"\b(?:aggregat\w*|in total|totall?ing|cumulative\w*|combined)\b", I)

# SEBI order-disclosure annexure (Listing Regulations Schedule III, Part A, para 4)
ANNEX_ENTITY = re.compile(r"name of the (?:entity|party|company|customer|client)\b[^:\n]{0,60}?(?:awarding|which has "
                          r"awarded|from whom|placing|awarded)[^:\n]{0,40}[:\-–]\s*(?:M/s\.?\s*)?([^\n]{3,90})", I)
ANNEX_GEOGRAPHY = re.compile(r"\bdomestic\s*(?:/|or)\s*international\b[^:\n]{0,40}[:\-–]\s*(domestic|international)", I)

# ---------------------------------------------------------------- counterparty, relationship, place (ported)

COUNTERPARTY_NAMED = re.compile(
    r"\b(?:from|by|with|(?:tenders?|orders?|contracts?) of)\s+(?:M/s\.?\s+)?((?:[A-Z][A-Za-z0-9&.\-]*|of|and|the)"
    r"(?:\s+(?:[A-Z][A-Za-z0-9&.\-]*|of|and|the|&|\(India\))){0,7})")
COUNTERPARTY_UNNAMED = re.compile(
    r"\b(?:a|an|one of the)\s+(?:leading|large|major|reputed|marquee|prestigious|global|domestic|international|"
    r"fortune \d+|european|us[- ]based|government)\b[^.,;]{0,40}?\b(?:customer|client|oem|player|company|utility|"
    r"psu|entity)\b", I)
CAPITALISED_STOPWORDS = {"The", "This", "We", "Our", "It", "In", "For", "During", "Company", "Board", "Management",
                         "Its", "Their", "These", "Such", "Exchange", "Exchanges", "Regulation", "Regulations",
                         "SEBI", "Listing", "Rs", "INR", "Ministry", "Crore", "Lakh"}
RELATED = re.compile(r"\b(?:its|our|the company'?s|the company’s)\s+(?:wholly[- ]owned\s+|step[- ]down\s+|material\s+)?"
                     r"subsidiar(?:y|ies)\b|\bgroup compan(?:y|ies)\b|\bpromoter group (?:entity|company)\b|"
                     r"\bjoint venture of the company\b|\b(?:is|are|being) (?:a )?related part(?:y|ies)\b", I)
ASSERT_RELATED = re.compile(r"(?:awarded by|whether)[^.\n]{0,80}related part(?:y|ies)[^.\n]{0,120}?[:\-–?]\s*yes\b", I)
ASSERT_UNRELATED = re.compile(
    r"(?:awarded by|whether)[^.\n]{0,80}related part(?:y|ies)[^.\n]{0,120}?(?:[:\-–]\s*|\?\s*)(?:no\b|not applicable|n\.?a\.?\b)|"
    r"\bnot (?:a )?related part(?:y|ies)\b|"
    r"promoter(?:s)?(?:\s*/\s*|\s+or\s+)promoter group (?:have|has|do not have|does not have) (?:no|any) interest|"
    r"\bdoes not (?:belong|fall) (?:to|within) (?:the )?promoter", I)
# "XYZ Ltd, a wholly owned subsidiary of the Company, has received ..." : the recipient, not the customer
SUBSIDIARY_RECIPIENT = re.compile(r"\b(?:(?:its|our|the company'?s|the company’s)\s+(?:wholly[- ]owned\s+|step[- ]down\s+|"
                                  r"material\s+)?subsidiar(?:y|ies)|(?:a\s+)?(?:wholly[- ]owned\s+|step[- ]down\s+|"
                                  r"material\s+)?subsidiary of the company)\b", I)
JOINT_VENTURE_RECIPIENT = re.compile(r"\b(?:joint venture|JV|consortium)\b[^.]{0,60}\b(?:received|bagged|secured|won|"
                                     r"awarded)\b", I)
FACILITY = re.compile(r"\b(?:at|in|of|for)\s+(?:the|our|its)\s+((?:[A-Z][\w-]*\s+){1,3})(?:plant|unit|facility|"
                      r"factory|works|site)\b")
FACILITY_BARE = re.compile(r"\b((?:[A-Z][\w-]*\s+){1,2})(?:plant|unit|facility|factory)\b(?!\s+(?:of|for)\b)")
FACILITY_AT = re.compile(r"\b(?:plant|unit|facility|factory|works|site|refinery|distillery)\s+(?:at|in)\s+"
                         r"((?:[A-Z][\w-]*\s?){1,2})")
SEGMENT = re.compile(r"\b(?:in|for|from) (?:the|our) ([a-z][a-z &/-]{2,40}?) (?:segment|division|business|vertical)\b", I)
CAPACITY_QTY = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*(MW|GW|MWp|GWh|MWh|KTPA|MTPA|TPA|TPD|tonnes? per (?:annum|day)|"
                          r"units? per (?:annum|month|year)|lakh units|million units|beds|rooms|stores|KLPD|MLD)\b", I)

# ---------------------------------------------------------------- other commercial families (new)

QUALIFICATION_CUE = re.compile(
    r"\bapproved (?:vendor|supplier|source|manufacturer)\b|\bvendor (?:registration|approval|empanell?ment)\b|"
    r"\b(?:qualified|empanell?ed|approved|registered|enlisted)\s+(?:as|with)\s+(?:an?\s+)?(?:the\s+)?"
    r"(?:approved\s+|preferred\s+|strategic\s+)?(?:vendor|supplier|source|partner|manufacturer)|"
    r"\b(?:qualified|empanell?ed)\s+(?:by|with)\s+(?:the\s+)?(?-i:[A-Z])|"
    r"\bqualification\b[^.]{0,60}\b(?:completed|successful|received|cleared|achieved)\b|"
    r"\bsuccessfully (?:completed|cleared|passed) (?:the )?(?:qualification|validation|(?:field |user )?trials?|"
    r"type tests?|PPAP|audit)\b|"
    r"\btype (?:approval|test(?:ing)?)\b[^.]{0,40}\b(?:received|completed|cleared|obtained)\b|"
    r"\b(?:received|obtained|granted|secured|got)\b[^.]{0,40}\b(?:approval|certification|accreditation|"
    r"clearance)\b[^.]{0,40}\b(?:from|by)\s+(?:the\s+)?(?:US ?FDA|USFDA|EU ?GMP|EMA|MHRA|TGA|WHO|PMDA|ANVISA|RDSO|DGCA|"
    r"CDSCO|BIS|ARAI|ICAT|Indian Railways|Ministry of Defence|MoD|DRDO|HAL|ISRO|BEE|PESO|NHAI)\b|"
    r"\b(?:ANDA|NDA|DMF|CEP)\b[^.]{0,30}\b(?:final )?(?:approval|approved)\b|"
    r"\bfinal approval from (?:the )?US ?FDA\b|\bPPAP\b|\bhomologation\b|"
    r"\b(?:EIR|establishment inspection report)\b|\b(?:VAI|NAI)\b status|"
    r"\bzero (?:483 )?observations\b|\bdesign win\b|\bnominated (?:as|for)\b[^.]{0,40}\b(?:supplier|programme|"
    r"platform)\b", I)
COMMERCIAL_START_CUE = re.compile(
    r"\b(?:commenc\w*|start(?:ed|s|ing)?|start of|beg[ai]n\w*|achiev\w*|declared)\s+(?:the\s+)?"
    r"(?:its\s+)?(?:commercial (?:production|operations?|supplies|dispatch(?:es)?|shipments?|sales)|"
    r"(?:production|operations) at|supplies to|deliveries to)\b|"
    r"\bcommercial operations? date\b|(?-i:\bCOD\b)|"
    r"\bfirst (?:commercial )?(?:shipment|dispatch|consignment|export (?:order|shipment)|supplies|delivery|batch)\b|"
    r"\b(?:commercial|regular|serial|mass|volume) production\b[^.]{0,40}\b(?:commenced|started|began|begun|commence|start)\b|"
    r"\bdeclared (?:as )?commercial\b|\bstarted (?:supplies|deliveries|shipments|dispatches)\b", I)
CAPACITY_CUE = re.compile(
    r"\bcapacity (?:expansion|addition|enhancement|augmentation)\b|"
    r"\bexpan(?:d|ding|sion of) (?:the |its |our )?(?:existing )?(?:manufacturing |production |installed )?capacity\b|"
    r"\bgreenfield\b|\bbrownfield\b|"
    r"\b(?:setting up|set up|establish(?:ing|ment of)?)\s+(?:of\s+)?(?:a\s+)?(?:new\s+)?(?:manufacturing\s+)?"
    r"(?:plant|facility|unit|factory|line)\b|"
    r"\bcapex (?:plan|of|programme|program)\b|\bcapital expenditure (?:of|plan)\b|\bdebottleneck\w*|"
    r"\b(?:commissioned|commissioning of)\b[^.]{0,60}\b(?:plant|unit|facility|line|capacity|MW|TPA|MTPA|furnace|"
    r"kiln|reactor)\b", I)
CAPACITY_FUNDED = re.compile(
    r"\bboard\b[^.]{0,40}\bapprov\w*|\b(?:funded|financed|to be funded) (?:through|by|from|out of)\b|"
    r"\bfinancial closure\b|\bterm loans? (?:sanctioned|tie-?up|tied up)\b|\bland (?:acquired|allotted|purchased)\b|"
    r"\b(?:orders?|purchase orders?) (?:placed|for) (?:the )?(?:plant and )?machinery\b|"
    r"\bconstruction (?:has )?(?:commenced|started|begun)\b|\bground ?breaking\b|\bbhoomi ?pujan\b", I)
CAPACITY_COMMISSIONED = re.compile(r"\b(?:commissioned|trial (?:run|production)s? (?:completed|commenced|started))\b", I)
MOU_INVESTMENT = re.compile(r"\b(?:invest(?:ment)?|capex|set(?:ting)? up|plant|facility|manufacturing unit)\b", I)
DEBT_CUE = re.compile(
    r"\b(?:pre-?paid|repaid|prepayment of|repayment of|retired|redeemed|redemption of)\b[^.]{0,60}"
    r"\b(?:loans?|debt|borrowings?|NCDs?|debentures?|term loans?)\b|"
    r"\b(?:net )?debt[- ]free\b|"
    r"\b(?:reduc\w+|lower\w*|declin\w*|cut)\b[^.]{0,30}\b(?:net )?(?:debt|borrowings?|finance costs?|"
    r"interest (?:costs?|burden|outgo))\b|"
    r"\b(?:net )?(?:debt|borrowings?|finance costs?|interest costs?)\b[^.]{0,30}\b(?:reduced|declined|came down|fell)\b|"
    r"\bcredit rating\b[^.]{0,60}\bupgrad\w*|\bupgrad\w+\b[^.]{0,60}\bcredit rating\b", I)
RATING = re.compile(r"\bcredit rating\b|\brating\b[^.]{0,20}\bupgrad", I)
EQUITY_FUNDED = re.compile(r"\b(?:QIP|qualified institutions? placement|rights issue|preferential (?:issue|allotment)|"
                           r"warrants?|IPO|initial public offer\w*|OFS|equity (?:raise|infusion|capital)|fund ?rais\w*|"
                           r"proceeds of the (?:issue|offer))\b", I)
LOSS_DRAG_CUE = re.compile(
    r"\b(?:divest\w*|sale|sold|exit\w*|clos(?:ed|ure|ing)|shut ?down|discontinu\w*|hiv(?:e|ed|ing) off|wound up|"
    r"winding up|strike off|struck off)\b[^.]{0,80}\bloss[- ]making\b|"
    r"\bloss[- ]making\b[^.]{0,80}\b(?:divest\w*|sold|exit\w*|closed|shut|discontinu\w*|hived off|wound up)\b", I)
PRICING_CUE = re.compile(
    r"\bprice (?:hike|increase|revision)s?\b|\bincreased (?:the |its |our )?(?:selling )?prices?\b|"
    r"\b(?:hike|increase)d? in (?:the )?(?:selling )?prices?\b|\btariff (?:hike|increase|order|revision)\b|"
    r"\bpassed on (?:the )?(?:cost|price|input)\b|\b(?:better|higher|improved) realisations?\b", I)
LAUNCH_CUE = re.compile(
    r"\b(?:launch(?:ed|es)?|introduc(?:ed|es)|unveil(?:ed|s))\b[^.]{0,60}\b(?:products?|brands?|models?|variants?|"
    r"drugs?|molecules?|formulations?|vehicles?|range|SKUs?|generics?|biosimilars?)\b|"
    r"\b(?:commercial|market|product) launch\b", I)
FINANCING_CUE = re.compile(
    r"\b(?:qualified institutions? placement|QIP|rights issue|preferential (?:issue|allotment)|"
    r"issue of (?:convertible )?warrants|allotment of (?:equity shares|warrants|convertible)|"
    r"fund ?rais(?:e|ing)|raising of funds)\b", I)

# ---------------------------------------------------------------- families

CORPORATE_APPROVAL = re.compile(r"\bapprov\w*\b[^.]{0,40}\b(?:board|audit committee|shareholders|members|directors|"
                                r"nomination|remuneration committee)\b", I)
INPUT_COST = re.compile(r"\b(?:raw[- ]materials?|RM|inputs?|commodit\w*|fuel|freight|ammonia|potash|crude|coal|gas|"
                        r"power cost)\b", I)
PASS_THROUGH = re.compile(r"\bpass(?:ed)? on\b|\btook (?:a |the )?price (?:hike|increase)|\brealisations?\b|"
                          r"\brealizations?\b", I)

# family -> (cue, event_type).  Checked in this order; one family per sentence.
FAMILIES: tuple[tuple[str, re.Pattern, str], ...] = (
    ("ORDER", ORDER_CUE, "ORDER"),
    ("COMMERCIAL_START", COMMERCIAL_START_CUE, "COMMERCIAL_START"),
    ("QUALIFICATION", QUALIFICATION_CUE, "CUSTOMER_QUALIFICATION"),
    ("LOSS_DRAG_REMOVAL", LOSS_DRAG_CUE, "LOSS_DRAG_REMOVAL"),
    ("CAPACITY", CAPACITY_CUE, "CAPACITY"),
    ("DEBT_REDUCTION", DEBT_CUE, "DEBT_REDUCTION"),
    ("PRICING", PRICING_CUE, "PRICING"),
    ("PRODUCT_LAUNCH", LAUNCH_CUE, "PRODUCT_LAUNCH"),
    ("FINANCING", FINANCING_CUE, "EQUITY_FINANCING"),
)
CONTEXT_FAMILIES = frozenset({"FINANCING"})          # recorded on the timeline; never a lead by themselves

# ---------------------------------------------------------------- policy thresholds (spec 18, development values)

POLICY = dict(
    material_ratio="0.10",          # annualised executable revenue / comparable annual revenue -> MATERIAL_POTENTIAL
    immaterial_ratio="0.02",        # whole firm order value / annual revenue at or below this -> IMMATERIAL
    amount_tolerance="0.02",        # same order when amounts agree within 2%
    max_gap_days=400,               # same order only within this many days of its first disclosure
    ambiguous_window_days=120,      # unnamed customer, same amount, within this window: maybe the same order
    stream_window_days=730,         # qualification / capacity / start events of one stream merge within this
    equity_funding_lookback_days=365,
    live_window_days=7,             # evaluations of disclosures older than this are reconstructions
    cooldown_days=30,               # spec 18.3 (reported; case handling comes with the queue)
)

STAGE_RANK = {"UNKNOWN": 0, "AMBITION": 1, "FUNDED_PLAN": 2, "QUALIFIED": 3, "BINDING_DEMAND": 4,
              "COMMERCIAL_SHIPMENT": 5, "REPEAT_SHIPMENT": 6}


def policy_hash() -> str:
    parts = [RULES_VERSION, repr(sorted(POLICY.items())), repr(sorted(STAGE_RANK.items()))]
    parts += [p.pattern for _, p, _ in FAMILIES]
    parts += [v.pattern for k, v in sorted(globals().items()) if isinstance(v, re.Pattern)]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()
