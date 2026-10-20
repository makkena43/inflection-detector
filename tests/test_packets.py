"""Triage packets: the financial snapshot, price summary and token budget (pure), then assembly from
the database at a shortlist's cutoff, versioning, export, recording and page retrieval."""

import json
from datetime import date, datetime, timedelta
from decimal import Decimal

import psycopg
import pytest

from inflection.asof import IST
from inflection.commercial import pipeline as commercial
from inflection.packets import contents as C
from inflection.packets import rules as R
from inflection.packets import pipeline
from inflection.triage import pipeline as triage
from test_commercial import SEBI_ANNEX, _filing, _seed

CR = Decimal(10) ** 7
CUTOFF = datetime(2026, 3, 23, tzinfo=IST)


def fact(metric, end, value, ptype="QUARTER", scope="CONSOLIDATED", kind="MONEY", pub="p1"):
    return dict(metric=metric, period_type=ptype, period_end=date.fromisoformat(end), scope=scope,
                value=None if value is None else Decimal(str(value)) * (CR if kind == "MONEY" else 1),
                currency="INR", scale="UNITS" if kind == "MONEY" else None, value_kind=kind,
                missing_reason=None if value is not None else "NOT_DISCLOSED",
                available_at=datetime.fromisoformat(end + "T18:00:00+05:30") + timedelta(days=40), publication_id=pub)


QUARTER_ENDS = ["2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31", "2025-03-31", "2025-06-30", "2025-09-30",
                "2025-12-31", "2026-03-31"]


# ---------------- financial snapshot ----------------

def test_snapshot_takes_eight_quarters_in_one_scope_with_growth_and_shares():
    facts = [fact("revenue", e, 100 + 10 * k) for k, e in enumerate(QUARTER_ENDS)]
    facts += [fact("pat", e, v) for e, v in zip(QUARTER_ENDS, [-5, 4, 4, 4, 5, 6, 6, 6, 7])]
    facts += [fact("revenue", "2025-12-31", 999, scope="STANDALONE")]
    facts += [fact("paid_up_capital", "2024-12-31", 10), fact("face_value", "2024-12-31", 10, kind="PER_SHARE"),
              fact("paid_up_capital", "2025-12-31", 11), fact("face_value", "2025-12-31", 10, kind="PER_SHARE")]
    s = C.financial_snapshot(facts)
    assert s["scope"] == "CONSOLIDATED" and s["other_scope_available"] == ["STANDALONE"]   # never mixed
    assert s["quarters"] == QUARTER_ENDS[-8:]
    assert s["rows"]["revenue"][-1]["value"] == "180.00"
    assert s["yoy"]["revenue"][-1]["value"] == "28.6"                                       # 180 on 140
    assert s["yoy"]["pat"][3] == dict(value=None, why="negative base: percentage growth is not meaningful; "
                                                        "report the absolute change")      # spec 15.7
    assert s["ttm"]["revenue"] == dict(value="660.00", period_end="2026-03-31")
    assert s["shares"]["value"] == "1.100" and s["shares"]["change_pct_vs_year_earlier"] == "10.0"


def test_snapshot_without_figures_says_so():
    assert C.financial_snapshot([])["status"] == "MISSING"
    s = C.financial_snapshot([fact("revenue", "2025-12-31", 50, scope="STANDALONE")])
    assert s["scope"] == "STANDALONE" and s["ttm"]["revenue"]["value"] is None


# ---------------- price summary ----------------

def _days(start, end):
    d = start
    while d <= end:
        if d.weekday() < 5:
            yield d
        d += timedelta(days=1)


def test_returns_are_adjusted_for_a_split_with_a_known_multiplier():
    rows = [(d, Decimal(200) if d < date(2025, 10, 1) else Decimal(110), Decimal(100000))
            for d in _days(date(2025, 1, 1), date(2026, 3, 20))]
    split = dict(kind="SPLIT", ex_date=date(2025, 10, 1), multiplier=Decimal("0.5"), subject="split 2:1")
    p = C.price_summary(rows, [split], date(2026, 3, 23), shares=Decimal(10) ** 7)
    assert p["status"] == "FOUND" and p["last_close"] == "110.00" and p["days_before_cutoff"] == 3
    assert p["returns_pct"]["12m"]["value"] == "10.0"                       # 100 adjusted -> 110, not -45%
    assert p["high_low_52w"] == dict(high="110.00", low="100.00")
    assert p["market_cap_cr"] == "110" and p["corporate_actions"][0]["price_multiplier"] == "0.5"

    unknown = dict(split, multiplier=None)
    q = C.price_summary(rows, [unknown], date(2026, 3, 23))
    assert q["returns_pct"]["12m"]["value"] is None and q["returns_pct"]["1m"]["value"] == "0.0"
    assert q["high_low_52w"]["high"] is None


def test_stale_and_missing_prices_are_flagged_not_hidden():
    rows = [(date(2026, 1, 2), Decimal(10), Decimal(100))]
    p = C.price_summary(rows, [], date(2026, 3, 23))
    assert p["status"] == "STALE"
    item = dict(slot="RANKED", has_symbol=True, stale=False)
    flags = {f["flag"] for f in C.risk_flags(item, [], [], [], dict(status="MISSING", reason="x"), p, [])}
    assert {"PRICE_STALE", "ILLIQUID", "NO_FINANCIALS"} <= flags
    assert C.price_summary([], [], date(2026, 3, 23))["status"] == "MISSING"


# ---------------- budget ----------------

def _head():
    return dict(cutoff=CUTOFF, mode="LIVE", week_start=date(2026, 3, 16), policy_version="triage-1",
                policy_hash="h", slot="RANKED", position=1, priority="P1", reason="order", note=None,
                corroborated=False, waiting_since=CUTOFF - timedelta(days=5), has_symbol=True, stale=False)


def _p(kind, n, event="e1", quote=None):
    return dict(kind=kind, evidence_id=f"{kind}-{n}", event_id=event, version_no=1, event_type="ORDER",
                stage="BINDING_DEMAND", relation="CONTRADICTS" if kind == "CONTRADICTS" else "SUPPORTS",
                assertion_type="COMMERCIAL_COMMITMENT", title="filing", source_url="https://x", page_no=1,
                quote=quote or f"passage {n} " + "words " * 60, text_artifact_id="t", document_version_id="d",
                publication_id="p", published_at=CUTOFF - timedelta(days=n))


def test_over_budget_cuts_oldest_earlier_passages_first_and_lists_the_cut():
    passages = [_p("TRIGGER", 1, quote="x" * 2000)] + [_p("CONTRADICTS", 2)] + [_p("PRIOR", n) for n in range(3, 60)]
    content, md = C.build(_head(), dict(issuer_id="i", name="ABC Ltd", label="ABC", isins=[], symbols=[]),
                          [], None, [], passages, [], dict(status="MISSING", reason="none"),
                          dict(status="MISSING", reason="none", corporate_actions=[]), {}, budget=3000)
    m = content["manifest"]
    assert m["token_estimate"] <= 3000 and C.estimate_tokens(md) == m["token_estimate"]
    kept = [p["evidence_id"] for p in content["prior_passages"]]
    assert kept == [f"PRIOR-{n}" for n in range(3, 3 + len(kept))]           # the newest survive
    assert m["truncation"][0]["section"] == "prior_passages" and m["truncation"][0]["omitted"] == 57 - len(kept)
    assert content["contradicting_passages"][0]["evidence_id"] == "CONTRADICTS-2"
    assert "[cut 1300 characters; read page 1]" in content["trigger_passages"][0]["quote"]
    assert m["completeness"] == "PARTIAL"
    assert "prior_passages: " in md and "may not recommend buying" in md


# ---------------- database ----------------

def _prices(db, iss):
    sec = db.execute("SELECT security_id FROM securities WHERE issuer_id = %s", (iss,)).fetchone()[0]
    with db.cursor() as cur:
        cur.executemany("""INSERT INTO prices (security_id, trade_date, provider, provider_version, close, volume,
                                               adjustment) VALUES (%s, %s, 'nse_bhavcopy', 't', %s, 50000, 'UNADJUSTED')""",
                        [(sec, d, 100 + (d - date(2025, 3, 1)).days // 30) for d in _days(date(2025, 3, 1),
                                                                                         date(2026, 3, 24))])


def test_assemble_from_the_database_at_the_shortlist_cutoff(db, tmp_path):
    iss, src = _seed(db)
    t1 = datetime(2026, 1, 20, 18, 5, tzinfo=IST)
    art = _filing(db, iss, src, 1, t1, ["Cover letter", SEBI_ANNEX])
    _filing(db, iss, src, 2, t1 + timedelta(days=1), [SEBI_ANNEX.replace("Disclosure", "Re-filed disclosure")])
    _filing(db, iss, src, 3, t1 + timedelta(days=60),
            ["The Board approved capex of Rs 500 crore for capacity expansion at the Hosur plant."],
            category="Outcome of Board Meeting")
    late = _filing(db, iss, src, 4, CUTOFF + timedelta(hours=3),             # after the cutoff: never in the packet
                   ["The Company has received a purchase order worth Rs 900 crore from Zeta Power Limited."])
    commercial.scan(db)
    commercial.resolve(db, now=t1 + timedelta(days=61))
    _prices(db, iss)
    now = CUTOFF + timedelta(days=2)
    week = triage.build(db, date(2026, 3, 16), now=now)
    assert [i["symbol"] for i in week["shortlist"]] == ["ABC"]

    out = pipeline.assemble(db, date(2026, 3, 18))
    pk = out["packets"][0]
    assert out["counts"] == {"NEW": 1} and pk["symbol"] == "ABC" and pk["tokens"] <= C.TOKEN_BUDGET
    shown = pipeline.show(db, date(2026, 3, 16), "abc")
    c, md = shown["content"], shown["markdown"]
    assert c["manifest"]["cutoff"] == "2026-03-22T18:30:00+00:00" and c["company"]["symbols"] == ["NSE:ABC"]
    assert c["events"][0]["event_type"] == "ORDER" and c["events"][0]["counterparty"].startswith("Maharashtra")
    assert any("7,781 solar pumps" in p["quote"] for p in c["trigger_passages"])
    assert "Zeta" not in md and "900 crore" not in md                         # published after the cutoff
    assert c["financials"]["scope"] == "CONSOLIDATED" and c["financials"]["rows"]["revenue"][-1]["value"] == "400.00"
    assert c["price"]["last_date"] == "2026-03-20"                            # Monday's close is not public yet
    assert any(d["text_artifact_id"] == str(art) for d in c["documents"])
    assert "## Financial snapshot" in md and "| revenue |" in md

    # same inputs, even read in another session time zone: the packet is kept; a figure public before the cutoff but recorded late: new version
    db.execute("SET TimeZone = 'Asia/Kolkata'")
    assert pipeline.assemble(db, date(2026, 3, 16))["counts"] == {"UNCHANGED": 1}
    db.execute("""INSERT INTO financial_facts (issuer_id, metric, period_end, scope, value, value_kind, currency, scale,
                                               period_type, available_at, provider, provider_version, content_hash)
                  VALUES (%s, 'pat', '2025-12-31', 'CONSOLIDATED', %s, 'MONEY', 'INR', 'UNITS', 'QUARTER', %s, 't', '1',
                          md5('late pat'))""", (iss, 40 * CR, datetime(2026, 2, 14, tzinfo=IST)))
    db.execute("""INSERT INTO financial_facts (issuer_id, metric, period_end, scope, value, value_kind, currency, scale,
                                               period_type, available_at, provider, provider_version, content_hash)
                  VALUES (%s, 'revenue', '2026-03-31', 'CONSOLIDATED', %s, 'MONEY', 'INR', 'UNITS', 'QUARTER', %s, 't',
                          '1', md5('future'))""", (iss, 900 * CR, CUTOFF + timedelta(days=30)))
    again = pipeline.assemble(db, date(2026, 3, 16))
    assert again["counts"] == {"UPDATED": 1}
    new = pipeline.show(db, date(2026, 3, 16), "ABC")
    assert new["content"]["financials"]["rows"]["pat"][-1]["value"] == "40.00"
    assert "2026-03-31" not in new["content"]["financials"]["quarters"]
    first, second = db.execute("""SELECT packet_id, supersedes_id FROM triage_packets ORDER BY created_at""").fetchall()
    assert second[1] == first[0]
    with pytest.raises(psycopg.errors.IntegrityConstraintViolation):
        db.execute("UPDATE triage_packets SET markdown = 'x'")               # earlier packets stay as they were

    # export for a chat, then record the result against the packet it was given
    exp = pipeline.export(db, date(2026, 3, 16), tmp_path)
    folder = tmp_path / "2026-03-16" / "01-ABC"
    assert exp["folders"] == [str(folder)]
    template = json.loads((folder / "triage_result.json").read_text())
    assert template["packet_hash"] == new["packet_hash"] and template["triage_action"] == ""
    assert set(C.RETURN_FIELDS) <= set(template)
    assert template["triage_rules_version"] == R.TRIAGE_RULES_VERSION == "triage-rules-3.4"
    md = (folder / "packet.md").read_text()
    assert "Triage rules triage-rules-3.4" in md and "size estimated from quantity" in md
    assert "## Valuation and margin (computed)" in md
    assert "At most three" not in md                          # no weekly limit on picks
    assert triage.record(db, date(2026, 3, 16), "ABC", "WATCH_MILESTONE")["triage_action"] == "WATCH_MILESTONE"
    assert db.execute("SELECT packet_id::text FROM triage_shortlist_items").fetchone()[0] == new["packet_id"]

    # the bounded retrieval pass
    got = pipeline.page(db, new["packet_id"], str(art), "1-2")
    assert [p["page"] for p in got["pages"]] == [1, 2] and "solar pumps" in got["pages"][1]["text"]
    assert "error" in pipeline.page(db, new["packet_id"], str(art), "1-6")
    assert "not public by the packet's cutoff" in pipeline.page(db, new["packet_id"], str(late), "1")["error"]


def test_assemble_needs_a_shortlist(db):
    assert "run triage build" in pipeline.assemble(db, date(2026, 3, 16))["error"]
