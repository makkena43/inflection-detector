"""Model check of commercial passages: does this passage disclose a new, company-specific event?

The rules in ``vocabulary`` find candidate passages cheaply and explainably, but they also catch
boilerplate, legal orders, accounting text, biographies, track records, period totals and garbled
pages.  ``verify_pending`` sends each unverified passage of the current rules version, with the text
around it and the filing's title, to Claude and stores a verdict in ``commercial_verifications``.
``resolve`` then leaves REJECTED passages off the company's events.  FINANCING passages are context
only (never a lead by themselves) and are not sent.

The client is injected (``anthropic.Anthropic()`` in the CLI) so tests run without network.  A
refusal or an unreadable answer is stored as UNCERTAIN and the passage is kept.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date
from typing import Optional

from . import vocabulary as V

VERIFIER_VERSION = "verify-1"
MODEL = "claude-opus-5-5"
SKIP_FAMILIES = ("FINANCING",)
CONTEXT_CHARS = 700
FAMILIES = [name for name, _, _ in V.FAMILIES] + ["NONE"]

SYSTEM = """You check passages that a rules engine pulled from Indian listed companies' stock-exchange filings \
(NSE/BSE announcements: press releases, board outcomes, investor presentations, call transcripts, letters).
The engine flags passages that may disclose a commercial event of one of these kinds:
- ORDER: an order, contract, letter of award/intent, L1 position, MoU or framework agreement with a customer.
- COMMERCIAL_START: commercial production, operations (COD), first shipments or supplies started.
- QUALIFICATION: a customer, regulator or certifier approved or qualified the company (e.g. USFDA ANDA approval, vendor approval).
- LOSS_DRAG_REMOVAL: exiting, selling or closing a loss-making business.
- CAPACITY: new or expanded plant capacity commissioned, funded or planned.
- DEBT_REDUCTION: debt repaid, prepaid, redeemed early, or net debt / finance cost reduced.
- PRICING: the company raised its own prices or tariffs, or passed on costs.
- PRODUCT_LAUNCH: the company launched a new product, brand or variant.

Decide whether the passage, read in its surrounding text, discloses such an event of the filing company
(or its subsidiary or joint venture) that is new or current as of the filing.

Answer REJECTED when the passage is any of: legal, court, tribunal, tax or regulator orders; boilerplate, \
form fields, cover-letter headers or addresses; accounting-policy text; director or employee biographies; \
cumulative track records or events from years before the filing; industry, government or market commentary; \
totals aggregated over a period (order inflow for the quarter, order book) presented as if one event; \
consumer, retail or broking "orders"; a customer's or third party's action rather than the company's; \
garbled or unreadable text; or a statement that the event did not happen or was delayed.
Answer CONFIRMED when it clearly discloses such an event. A forward-looking but specific plan of the company \
(e.g. a board-approved capacity expansion) is CONFIRMED.
Answer UNCERTAIN only when the text genuinely does not let you decide.

Give "family" as the kind the event actually is (it may differ from the engine's guess), or NONE when \
REJECTED. Keep "reason" to one short sentence."""

SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["CONFIRMED", "REJECTED", "UNCERTAIN"]},
        "family": {"type": "string", "enum": FAMILIES},
        "reason": {"type": "string"},
    },
    "required": ["verdict", "family", "reason"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Passage:
    mention_id: str
    company: str
    published: Optional[date]
    title: str
    family: str
    quote: str
    context: str


@dataclass(frozen=True)
class Verdict:
    verdict: str
    family: Optional[str]
    reason: str
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def context_window(page: str, quote: str, chars: int = CONTEXT_CHARS) -> str:
    """The quote with up to ``chars`` characters either side, on whitespace-normalised page text."""
    body, q = _norm(page), _norm(quote)
    at = body.find(q)
    if at < 0:
        return q
    a, b = max(0, at - chars), min(len(body), at + len(q) + chars)
    return ("…" if a else "") + body[a:b] + ("…" if b < len(body) else "")


def user_message(p: Passage) -> str:
    return (f"Company: {p.company}\nFiling date: {p.published or 'unknown'}\nFiling title: {p.title or '-'}\n"
            f"Engine's guess: {p.family}\n\nPassage:\n<<<{_norm(p.quote)}>>>\n\n"
            f"Surrounding text:\n<<<{p.context}>>>")


def ask(client, p: Passage, model: str = MODEL) -> Verdict:
    """One verdict from the model.  Refusals and unreadable answers come back UNCERTAIN."""
    response = client.beta.messages.create(
        model=model,
        max_tokens=2048,
        system=[{"type": "text", "text": SYSTEM, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": user_message(p)}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    usage = getattr(response, "usage", None)
    tokens = (getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None))
    if response.stop_reason == "refusal":
        return Verdict("UNCERTAIN", None, "model declined to answer", *tokens)
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        data = json.loads(text)
        verdict, family, reason = data["verdict"], data["family"], str(data["reason"])[:500]
    except (ValueError, KeyError, TypeError):
        return Verdict("UNCERTAIN", None, f"unreadable answer ({response.stop_reason})", *tokens)
    if verdict not in ("CONFIRMED", "REJECTED", "UNCERTAIN") or family not in FAMILIES:
        return Verdict("UNCERTAIN", None, "answer outside the schema", *tokens)
    return Verdict(verdict, None if family == "NONE" else family, reason, *tokens)


_PENDING = """
SELECT m.mention_id, coalesce(i.legal_name, ''), (m.published_at AT TIME ZONE 'Asia/Kolkata')::date,
       coalesce(p.title, ''), m.family, m.quote, coalesce(tp.body, '')
  FROM commercial_mentions m
  LEFT JOIN issuers i USING (issuer_id)
  LEFT JOIN document_publications p USING (publication_id)
  LEFT JOIN text_pages tp ON tp.text_artifact_id = m.text_artifact_id AND tp.page_no = m.page_no
 WHERE m.rules_version = %(rv)s AND m.family <> ALL(%(skip)s)
   AND NOT EXISTS (SELECT 1 FROM commercial_verifications v
                    WHERE v.mention_id = m.mention_id AND v.verifier_version = %(vv)s)
   AND (%(lo)s::timestamptz IS NULL OR m.published_at >= %(lo)s)
   AND (%(hi)s::timestamptz IS NULL OR m.published_at < %(hi)s)
 ORDER BY m.published_at, m.mention_id
 LIMIT %(limit)s"""


def pending(conn, lo=None, hi=None, limit: Optional[int] = None) -> list[Passage]:
    rows = conn.execute(_PENDING, dict(rv=V.RULES_VERSION, skip=list(SKIP_FAMILIES), vv=VERIFIER_VERSION,
                                       lo=lo, hi=hi, limit=limit)).fetchall()
    return [Passage(str(mid), company, day, title, family, quote, context_window(body, quote))
            for mid, company, day, title, family, quote, body in rows]


def store(conn, p: Passage, v: Verdict, model: str = MODEL) -> None:
    conn.execute(
        """INSERT INTO commercial_verifications (mention_id, verifier_version, verdict, family, reason, model,
                                                  input_tokens, output_tokens)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s) ON CONFLICT (mention_id, verifier_version) DO NOTHING""",
        (p.mention_id, VERIFIER_VERSION, v.verdict, v.family, v.reason, model, v.input_tokens, v.output_tokens))


def verify_pending(conn, client, lo=None, hi=None, limit: Optional[int] = None, workers: int = 4,
                   model: str = MODEL, progress=None) -> Counter:
    """Verify unverified passages of the current rules version; the model calls run in parallel, the
    database writes stay on this connection."""
    passages = pending(conn, lo, hi, limit)
    out: Counter = Counter()

    def one(p: Passage) -> tuple[Passage, Verdict]:
        try:
            return p, ask(client, p, model)
        except Exception as e:                      # network or API error: retried on the next run
            return p, Verdict("ERROR", None, f"{type(e).__name__}: {e}"[:300])

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for i, (p, v) in enumerate(pool.map(one, passages), 1):
            if v.verdict == "ERROR":
                out["ERROR"] += 1
            else:
                store(conn, p, v, model)
                out[v.verdict] += 1
                out["input_tokens"] += v.input_tokens or 0
                out["output_tokens"] += v.output_tokens or 0
            if progress and i % 50 == 0:
                progress(i, len(passages), dict(out))
    return out


REJECTED_SQL = """EXISTS (SELECT 1 FROM commercial_verifications v WHERE v.mention_id = m.mention_id
                          AND v.verifier_version = '{vv}' AND v.verdict = 'REJECTED')""".format(vv=VERIFIER_VERSION)
