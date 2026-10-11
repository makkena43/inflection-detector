"""The weekly triage shortlist: slots from the combined queue, caps that defer visibly, aging,
cooldown after a triage, stale marking, and the database steps."""

import json
from datetime import date, datetime, timedelta

from inflection import queue
from inflection.sources.common import IST
from inflection.triage import pipeline
from inflection.triage import rules as R

WEEK = date(2026, 10, 5)                                       # a Monday
CUTOFF = datetime(2026, 10, 12, tzinfo=IST)


def line(n, cls, waited=3, alloc="RANKED", within=(1, 0, 0), triggers=()):
    return dict(issuer_id=f"iss-{n:03d}", symbol=f"S{n}", name=f"Company {n}", priority=cls, corroborated=False,
                waiting_since=CUTOFF - timedelta(days=waited), latest=CUTOFF, reason=f"reason {n}",
                within_class=within, allocations=[alloc], evaluation_ids=[], trigger_event_version_ids=list(triggers),
                commercial_triggers=list(triggers))


def slots(items):
    return {i["issuer_id"]: i["slot"] for i in items}


# ---------------- allocation ----------------

def test_no_fixed_company_count_by_default():
    lines = [line(n, "P2") for n in range(40)] + [line(100, "U0"), line(101, "D")]
    items = R.allocate(lines, WEEK, CUTOFF, R.policy())
    s = slots(items)
    assert sum(v == "RANKED" for v in s.values()) == 40 and s["iss-100"] == "UPDATE" and s["iss-101"] == "DATA_REPAIR"
    assert [i["slot"] for i in items[:2]] == ["UPDATE", "RANKED"]               # updates come first
    assert [i["position"] for i in items if i["position"]] == list(range(1, 42))


def test_ranked_order_is_class_milestone_stage_band_then_waiting_time():
    lines = [line(1, "P2", waited=50), line(2, "P1", waited=1), line(3, "P2", waited=5, within=(0, -6, -2)),
             line(4, "P2", waited=60)]
    order = [i["issuer_id"] for i in R.allocate(lines, WEEK, CUTOFF, R.policy()) if i["slot"] == "RANKED"]
    assert order == ["iss-002", "iss-003", "iss-004", "iss-001"]


def test_cap_defers_visibly_and_exploration_takes_the_oldest_not_alphabetic():
    """Spec 15.13: a queue overrun defers visibly; nobody is dropped because of alphabetic order."""
    lines = [line(n, "P2", waited=n) for n in range(1, 11)] + [line(50, "P3", waited=200, alloc="EXPLORATION")]
    p = R.policy(ranked_cap=3, exploration=2)
    items = R.allocate(lines, WEEK, CUTOFF, p)
    s = slots(items)
    assert [k for k, v in s.items() if v == "RANKED"] == ["iss-010", "iss-009", "iss-008"]   # equal rank: longest wait
    assert {k for k, v in s.items() if v == "EXPLORATION"} == {"iss-050", "iss-007"}
    assert sum(v == "DEFERRED" for v in s.values()) == 6 and len(items) == 11
    summ = R.summary(items, WEEK, CUTOFF, p)
    assert summ["slots"]["DEFERRED"] == 6 and summ["expected_delay_weeks"] == 2
    assert summ["warnings"] and summ["shortlisted"] == 5


def test_exploration_ignores_materiality():
    """A small quantified catalyst does not outrank an older unquantified one in exploration."""
    lines = [line(1, "P2", waited=5, within=(0, -6, -3)), line(2, "P2", waited=40, within=(1, 0, 0)),
             line(3, "P2", waited=1)]
    s = slots(R.allocate(lines, WEEK, CUTOFF, R.policy(ranked_cap=1, exploration=1)))
    assert (s["iss-001"], s["iss-002"], s["iss-003"]) == ("RANKED", "EXPLORATION", "DEFERRED")


def test_watch_companies_rotate_through_the_audit_sample():
    lines = [line(n, "P3", alloc="NONE") for n in range(20)]
    weeks = [WEEK + timedelta(weeks=k) for k in range(4)]
    picked = [{k for k, v in slots(R.allocate(lines, w, CUTOFF, R.policy())).items() if v == "AUDIT"} for w in weeks]
    assert all(len(p) == 2 for p in picked) and len(set().union(*picked)) > 2


def test_stale_companies_stay_queued_and_are_marked():
    items = R.allocate([line(1, "P2", waited=120), line(2, "P3", alloc="NONE", waited=400)], WEEK, CUTOFF,
                       R.policy(audit=0))
    s = {i["issuer_id"]: i for i in items}
    assert s["iss-001"]["slot"] == "RANKED" and s["iss-001"]["stale"] and "STALE_UNRESEARCHED" in s["iss-001"]["note"]
    assert s["iss-002"]["slot"] == "WATCH" and s["iss-002"]["stale"]


def test_cooldown_after_triage_unless_something_material_changed():
    last = R.Triaged(CUTOFF - timedelta(days=7), "P2", {"v1"})
    p = R.policy()
    triaged = {f"iss-{n:03d}": last for n in range(1, 6)}
    lines = [line(1, "P2"), line(2, "P1"), line(3, "U0"), line(4, "P2", triggers=["v1", "v2"]),
             line(5, "P2", triggers=["v1"])]
    s = slots(R.allocate(lines, WEEK, CUTOFF, p, triaged))
    assert s == {"iss-001": "COOLDOWN", "iss-002": "RANKED", "iss-003": "UPDATE", "iss-004": "RANKED",
                 "iss-005": "COOLDOWN"}
    old = R.Triaged(CUTOFF - timedelta(days=31), "P2", set())
    assert slots(R.allocate([line(1, "P2")], WEEK, CUTOFF, p, {"iss-001": old})) == {"iss-001": "RANKED"}


# ---------------- database ----------------

def _issuer(db, sym):
    iss = db.execute("INSERT INTO issuers (legal_name) VALUES (%s) RETURNING issuer_id", (f"{sym} Ltd",)).fetchone()[0]
    sec = db.execute("INSERT INTO securities (issuer_id, isin) VALUES (%s, %s) RETURNING security_id",
                     (iss, f"INE{sym}A01011")).fetchone()[0]
    db.execute("""INSERT INTO identifier_history (security_id, exchange, kind, value, valid_from, source)
                  VALUES (%s, 'NSE', 'SYMBOL', %s, '2010-01-01', 'test')""", (sec, sym))
    return iss


def _evaluation(db, iss, at, cls, route="COMMERCIAL", alloc="RANKED", ranking=None, triggers=()):
    db.execute("""INSERT INTO candidate_evaluations (run_id, issuer_id, as_of, mode, policy_version, route,
                                                     components, outcome, reasons, policy_hash, priority_class,
                                                     queue_allocation, ranking_tuple, trigger_event_version_ids,
                                                     content_hash)
                  VALUES (gen_random_uuid(), %s, %s, 'LIVE', 'test-1', %s, '{}', 'ADMIT', %s, 'h', %s, %s, %s,
                          %s::uuid[], 'c')""",
               (iss, at, route, [f"{cls} lead"], cls, alloc,
                json.dumps(ranking or [0, 1, 0, 0, at.isoformat(), "t"]), list(triggers)))


def test_build_show_record_and_cooldown_next_week(db):
    t = lambda d: datetime.fromisoformat(d + "T18:00:00+05:30")             # noqa: E731
    a, b, c, d = (_issuer(db, s) for s in ("AAA", "BBB", "CCC", "DDD"))
    _evaluation(db, a, t("2026-08-01"), "P3", route="FINANCIAL", alloc="NONE")
    _evaluation(db, a, t("2026-10-06"), "P2")
    _evaluation(db, b, t("2026-10-07"), "P1", ranking=[1, 0, -5, -2, "x", "t"])
    _evaluation(db, c, t("2026-10-08"), "D", alloc="NONE")
    _evaluation(db, d, t("2026-10-15"), "P1")                               # after the first cutoff
    now = datetime(2026, 10, 25, tzinfo=IST)

    preview = pipeline.build(db, WEEK + timedelta(days=3), dry_run=True, now=now)
    assert preview["dry_run"] and db.execute("SELECT count(*) FROM triage_shortlists").fetchone() == (0,)
    out = pipeline.build(db, WEEK, now=now)
    assert out["cutoff"] == CUTOFF.isoformat()
    assert [(i["symbol"], i["slot"], i["priority"]) for i in out["shortlist"]] == [("BBB", "RANKED", "P1"),
                                                                                   ("AAA", "RANKED", "P2")]
    assert out["shortlist"][1]["waiting_days"] == 71                        # waiting since the August P3
    assert out["summary"]["slots"] == {"RANKED": 2, "DATA_REPAIR": 1}
    assert pipeline.build(db, WEEK, now=now)["existing"]                    # one shortlist per week
    assert len(pipeline.show(db, WEEK, everything=True)["shortlist"]) == 3

    assert "error" in pipeline.record(db, WEEK, "CCC", "DATA_REPAIR")       # not shortlisted
    assert pipeline.record(db, WEEK, "aaa", "WATCH_MILESTONE", "wait for Q3")["triage_action"] == "WATCH_MILESTONE"
    assert "already triaged" in pipeline.record(db, WEEK, "AAA", "REJECT_WITH_REASON")["error"]
    assert pipeline.record(db, WEEK, "BBB", "DEFER_BUDGET")["triage_action"] == "DEFER_BUDGET"
    assert db.execute("SELECT count(*) FROM audit_log WHERE action = 'TRIAGE_RECORDED'").fetchone() == (2,)

    # next week: AAA's earlier evaluations were triaged, a new unchanged P2 waits out the cooldown;
    # BBB was deferred for budget and keeps its waiting time; DDD arrives
    _evaluation(db, a, t("2026-10-14"), "P2")
    nxt = pipeline.build(db, WEEK + timedelta(weeks=1), now=now)
    every = {i["symbol"]: i for i in pipeline.show(db, WEEK + timedelta(weeks=1), everything=True)["shortlist"]}
    assert every["AAA"]["slot"] == "COOLDOWN" and every["AAA"]["waiting_days"] == 4
    assert every["BBB"]["slot"] == "RANKED" and every["BBB"]["waiting_days"] == 11
    assert every["DDD"]["slot"] == "RANKED"
    assert nxt["summary"]["new_this_week"] == 2                             # AAA's new line and DDD


def test_queue_companies_reports_waiting_since(db):
    iss = _issuer(db, "AAA")
    _evaluation(db, iss, datetime(2026, 9, 1, 18, tzinfo=IST), "P3", alloc="NONE")
    _evaluation(db, iss, datetime(2026, 10, 1, 18, tzinfo=IST), "P2")
    q = queue.companies(db)[0]
    assert q["priority"] == "P2" and q["waiting_since"].startswith("2026-09-01")


def test_a_company_without_a_symbol_is_named_by_isin_and_can_be_recorded(db):
    iss = db.execute("INSERT INTO issuers (legal_name) VALUES ('KSS Limited') RETURNING issuer_id").fetchone()[0]
    db.execute("INSERT INTO securities (issuer_id, isin) VALUES (%s, 'INE216B01012')", (iss,))
    _evaluation(db, iss, datetime(2026, 10, 8, 18, tzinfo=IST), "P2")
    out = pipeline.build(db, WEEK, now=datetime(2026, 10, 11, 9, tzinfo=IST))
    item = out["shortlist"][0]
    assert item["symbol"] == "INE216B01012" and "no exchange symbol on record" in item["note"]
    assert pipeline.record(db, WEEK, "ine216b01012", "DATA_REPAIR")["triage_action"] == "DATA_REPAIR"
