"""The shadow replay: outcome arithmetic and summaries (pure), then a replay over fixture weeks that
must stay point-in-time, simulate triage cooldown, take no live actions, and measure outcomes."""

import re
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from inflection.asof import IST
from inflection.replay import pipeline
from inflection.replay import rules as R
from test_triage import _evaluation, _issuer

P = R.policy()


def days(start, end, price):
    """Weekday closes from ``start`` to ``end``; ``price`` maps a date to a close."""
    d, out = start, []
    while d <= end:
        if d.weekday() < 5:
            out.append((d, Decimal(str(price(d)))))
        d += timedelta(days=1)
    return out


# ---------------- outcomes ----------------

def test_split_adjusted_return_drawdown_and_entry_after_the_lag():
    s = days(date(2022, 1, 3), date(2022, 12, 30), lambda d: 100 if d < date(2022, 3, 1) else
             (40 if d < date(2022, 6, 1) else 60))
    split = dict(kind="SPLIT", ex_date=date(2022, 3, 1), multiplier=Decimal("0.5"), reconciled=True)
    cutoff = datetime(2022, 1, 10, tzinfo=IST)
    target = R.entry_target(cutoff, P)
    assert target == date(2022, 1, 17)                                      # the week triage takes
    o = R.outcome(s, [split], target, 182, date(2022, 12, 30), P)
    assert o.status == "VERIFIED" and o.entry_date == date(2022, 1, 17) and o.multiplier == Decimal("0.5")
    assert o.price_return == Decimal("0.2000")                              # 50 adjusted -> 60
    assert o.max_drawdown == Decimal("-0.2000")                             # 50 -> 40


def test_unknown_or_unreconciled_actions_and_rights_are_not_verified():
    s = days(date(2022, 1, 3), date(2022, 12, 30), lambda d: 100)
    unknown = dict(kind="BONUS", ex_date=date(2022, 3, 1), multiplier=None, reconciled=False)
    o = R.outcome(s, [unknown], date(2022, 1, 17), 182, date(2022, 12, 30), P)
    assert o.status == "UNVERIFIED" and o.price_return is None              # never a guessed number
    loose = dict(unknown, multiplier=Decimal("0.5"))
    assert R.outcome(s, [loose], date(2022, 1, 17), 182, date(2022, 12, 30), P).status == "UNVERIFIED"
    rights = dict(kind="RIGHTS", ex_date=date(2022, 3, 1), multiplier=None, reconciled=False)
    o = R.outcome(s, [rights], date(2022, 1, 17), 182, date(2022, 12, 30), P)
    assert o.status == "UNVERIFIED" and o.price_return == 0 and "rights" in o.notes[0]
    div = dict(kind="DIVIDEND", ex_date=date(2022, 3, 1), multiplier=None, reconciled=False)
    o = R.outcome(s, [div], date(2022, 1, 17), 182, date(2022, 12, 30), P)
    assert o.status == "VERIFIED" and "not included" in o.notes[0]


def test_incomplete_no_price_and_stopped_trading():
    s = days(date(2022, 1, 3), date(2022, 4, 29), lambda d: 100 - (d.toordinal() % 7))
    assert R.outcome(s, [], date(2022, 1, 17), 365, date(2022, 6, 30), P).status == "INCOMPLETE"
    assert R.outcome(s, [], date(2022, 6, 1), 30, date(2022, 12, 30), P).status == "NO_PRICE"
    o = R.outcome(s, [], date(2022, 1, 17), 182, date(2022, 12, 30), P)
    assert o.status == "STOPPED_TRADING" and o.exit_date == date(2022, 4, 29) and o.price_return is not None


def test_winner_status_window():
    start = date(2022, 7, 1)
    assert R.winner_status([date(2022, 3, 7)], [], True, True, start, P) == ("SHORTLISTED", date(2022, 3, 7))
    assert R.winner_status([date(2021, 6, 7)], [date(2022, 6, 6)], True, False, start, P)[0] == "QUEUED_NOT_SHORTLISTED"
    assert R.winner_status([], [], True, False, start, P)[0] == "FIGURES_NO_NOMINATION"
    assert R.winner_status([], [], False, False, start, P)[0] == "NO_COVERAGE"


def test_summary_hides_holdout_returns_until_revealed():
    w1, w2 = date(2022, 1, 3), date(2023, 1, 2)
    items = [dict(week_start=w1, issuer_id="a", slot="RANKED", shortlisted=True, priority_class="P2",
                  routes=["FINANCIAL"], period="DEVELOPMENT"),
             dict(week_start=w2, issuer_id="b", slot="RANKED", shortlisted=True, priority_class="P2",
                  routes=["FINANCIAL"], period="HOLDOUT"),
             dict(week_start=w1, issuer_id="c", slot="WATCH", shortlisted=False, priority_class="P3",
                  routes=["FINANCIAL"], period="DEVELOPMENT")]
    R.mark_first_time(items)
    out = [dict(week_start=w1, issuer_id="a", horizon="3m", status="VERIFIED", price_return=Decimal("0.6"),
                excess_return=Decimal("0.5"), max_drawdown=Decimal("-0.1")),
           dict(week_start=w2, issuer_id="b", horizon="3m", status="VERIFIED", price_return=Decimal("-0.6"),
                excess_return=Decimal("-0.5"), max_drawdown=Decimal("-0.7")),
           dict(week_start=w1, issuer_id="c", horizon="3m", status="INCOMPLETE", price_return=None)]
    s = R.summarise(items, out, P)
    assert s["holdout_outcomes_hidden"] == {"3m": 1}
    g = s["groups"]["shortlisted"]["3m"]
    assert (g["measured"], g["median_return_pct"], g["big_move_pct"], g["beat_universe_median_pct"]) == \
        (1, "60.0", "100.0", "100.0")
    assert s["groups"]["not_shortlisted_new_evidence"]["3m"]["by_status"] == {"INCOMPLETE": 1}
    assert s["groups"]["shortlisted_first_time"]["3m"]["measured"] == 1
    full = R.summarise(items, out, P, include_holdout=True)["groups"]["shortlisted"]["3m"]
    assert full["measured"] == 2 and full["lost_half_pct"] == "50.0"


def test_weeks_and_periods():
    w = R.weeks(date(2021, 1, 6), date(2021, 1, 18))
    assert [x[0] for x in w] == [date(2021, 1, 4), date(2021, 1, 11), date(2021, 1, 18)]
    assert w[0][1] == datetime(2021, 1, 11, tzinfo=IST)
    assert R.period(date(2024, 1, 1), date(2024, 1, 1)) == "HOLDOUT" and R.period(date(2023, 12, 25), None) == \
        "DEVELOPMENT"


def test_outcomes_stay_out_of_analyst_facing_code():
    """Spec 12: future outcomes are stored apart; only the replay reads them."""
    src = Path(__file__).parent.parent / "src" / "inflection"
    readers = {p.relative_to(src).parts[0] for p in src.rglob("*.py")
               if re.search(r"shadow_replay_(outcomes|winners)", p.read_text())}
    assert readers == {"replay"}


# ---------------- database ----------------

def _prices(db, iss, closes, provider="nse_bhavcopy"):
    sec = db.execute("SELECT security_id FROM securities WHERE issuer_id = %s", (iss,)).fetchone()[0]
    with db.cursor() as cur:
        cur.executemany("""INSERT INTO prices (security_id, trade_date, provider, provider_version, close, volume,
                                               adjustment) VALUES (%s, %s, %s, 'test', %s, 100000, 'UNADJUSTED')""",
                        [(sec, d, provider, c) for d, c in closes])
    return sec


def test_replay_is_point_in_time_simulates_cooldown_and_takes_no_actions(db):
    t = lambda d: datetime.fromisoformat(d + "T18:00:00+05:30")             # noqa: E731
    names = ("AAA", "BBB", "CCC", "DDD", "EEE", "FFF")
    a, b, c, d, e, f = (_issuer(db, s) for s in names)
    start, end = date(2021, 12, 1), date(2023, 6, 30)
    _prices(db, a, days(start, end, lambda x: 100 if x < date(2022, 2, 1) else 200))      # doubles
    sec_b = _prices(db, b, days(start, end, lambda x: 100 if x < date(2022, 3, 1) else 45))
    db.execute("""INSERT INTO corporate_actions (security_id, kind, ex_date, details, provider, provider_version,
                                                 reconciled)
                  VALUES (%s, 'SPLIT', '2022-03-01', '{"price_multiplier": "0.5", "subject": "split"}', 'nse', 't',
                          true)""", (sec_b,))
    _prices(db, d, days(start, end, lambda x: 100 if x < date(2022, 4, 1) else 400))      # a missed winner
    for iss in (e, f):
        _prices(db, iss, days(start, end, lambda x: 100))                                  # flat universe
    _evaluation(db, a, t("2022-01-04"), "P2", route="FINANCIAL")
    _evaluation(db, b, t("2022-01-05"), "P3", route="FINANCIAL", alloc="NONE")
    _evaluation(db, a, t("2022-01-19"), "P2", route="FINANCIAL")             # within a's cooldown
    _evaluation(db, c, t("2022-01-26"), "P1")                                # no prices at all
    db.execute("""INSERT INTO financial_facts (issuer_id, metric, period_start, period_end, scope, value, value_kind,
                                               currency, scale, period_type, available_at, provider,
                                               provider_version, content_hash)
                  VALUES (%s, 'revenue', '2021-10-01', '2021-12-31', 'CONSOLIDATED', 1, 'MONEY', 'INR', 'UNITS',
                          'QUARTER', '2022-02-10T18:00:00+05:30', 'nse_xbrl', 'test', 'h')""", (d,))
    now = datetime(2026, 10, 11, tzinfo=IST)

    out = pipeline.run(db, date(2022, 1, 3), date(2022, 2, 7), now=now, horizons={"3m": 91, "12m": 365},
                       triage=dict(audit=1))
    rid = out["replay_id"]
    for table in ("triage_shortlists", "triage_shortlist_items", "triage_packets", "research_cases"):
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table

    items = {(w, s): (slot, short) for w, s, slot, short in db.execute(
        f"""SELECT i.week_start, {pipeline.queue.LABEL.format(col='i.issuer_id')}, i.slot, i.shortlisted
              FROM shadow_replay_items i WHERE replay_id = %s""", (rid,)).fetchall()}
    w1, w2, w3, w4 = (date(2022, 1, 3) + timedelta(weeks=k) for k in range(4))
    assert items[(w1, "AAA")] == ("RANKED", True)
    assert items[(w1, "BBB")] == ("AUDIT", True)                             # the one-company watch sample
    assert (w1, "CCC") not in items and items[(w4, "CCC")] == ("RANKED", True)   # not before it was public
    assert (w2, "AAA") not in items                                          # triaged, nothing new
    assert items[(date(2022, 2, 7), "AAA")] == ("RANKED", True)              # the cooldown has run out
    assert items[(w3, "AAA")] == ("COOLDOWN", False)                         # new, unchanged: comparison group
    weeks = pipeline.weeks(db, rid)
    assert len(weeks) == 6 and weeks[0]["shortlisted"] == 2 and weeks[0]["coverage"]["nse_bhavcopy_days"] == 5
    assert out["coverage"]["weeks_with_announcements"] == 0 and "commercial route" in out["coverage"]["warnings"][0]

    o = {(w, s, h): r for w, s, h, *r in db.execute(
        f"""SELECT o.week_start, {pipeline.queue.LABEL.format(col='o.issuer_id')}, o.horizon, o.status,
                   o.price_return, o.benchmark_return, o.excess_return, o.entry_date
              FROM outcomes.shadow_replay_outcomes o WHERE replay_id = %s""", (rid,)).fetchall()}
    status, ret, bench, excess, entry = o[(w1, "AAA", "3m")]
    assert (status, ret, entry) == ("VERIFIED", Decimal("1.0000"), date(2022, 1, 17))
    assert bench == Decimal("0.0000") and excess == Decimal("1.0000")        # median of the five: +100%, -10%, +300%, 0, 0
    assert o[(w1, "BBB", "3m")][:2] == ["VERIFIED", Decimal("-0.1000")]      # 50 adjusted -> 45, not -55%
    assert o[(w4, "CCC", "3m")][0] == "NO_PRICE"
    s = out["summary"]["outcomes"]["groups"]
    assert s["shortlisted"]["3m"]["measured"] == 3 and s["slot:COOLDOWN"]["3m"]["measured"] == 1

    win = {w["symbol"]: w for w in pipeline.winners(db, rid)}
    assert win["AAA"]["status"] == "SHORTLISTED" and win["AAA"]["window_start"] == "2022-01-01"
    assert win["DDD"]["status"] == "FIGURES_NO_NOMINATION" and win["DDD"]["return_pct"] == "300.0"
    assert "BBB" not in win and "EEE" not in win
    assert out["summary"]["winners"]["by_status"] == {"FIGURES_NO_NOMINATION": 1, "SHORTLISTED": 1}


def test_actual_system_replay_needs_the_evaluation_stored_by_the_cutoff(db):
    a = _issuer(db, "AAA")
    _evaluation(db, a, datetime(2022, 1, 4, 18, tzinfo=IST), "P2")          # stored today, long after
    now = datetime(2026, 10, 11, tzinfo=IST)
    recon = pipeline.run(db, date(2022, 1, 3), date(2022, 1, 3), now=now, dry_run=True)
    actual = pipeline.run(db, date(2022, 1, 3), date(2022, 1, 3), mode="ACTUAL_SYSTEM_REPLAY", now=now, dry_run=True)
    assert recon["summary"]["shortlisted"] == 1 and actual["summary"]["shortlisted"] == 0
    assert db.execute("SELECT count(*) FROM shadow_replays").fetchone() == (0,)    # dry run stores nothing


def test_report_reveals_holdout_only_on_request_and_logs_it(db):
    a = _issuer(db, "AAA")
    _prices(db, a, days(date(2021, 12, 1), date(2022, 9, 30), lambda x: 100 if x < date(2022, 2, 1) else 150))
    _evaluation(db, a, datetime(2022, 1, 4, 18, tzinfo=IST), "P2")
    now = datetime(2026, 10, 11, tzinfo=IST)
    out = pipeline.run(db, date(2022, 1, 3), date(2022, 1, 3), holdout_from=date(2022, 1, 1), now=now,
                       horizons={"3m": 91}, big_move_horizon="3m")
    rep = pipeline.report(db)
    assert rep["replay_id"] == out["replay_id"] and rep["summary"]["outcomes"]["holdout_outcomes_hidden"] == {"3m": 1}
    assert "shortlisted" not in rep["summary"]["outcomes"]["groups"]
    shown = pipeline.report(db, out["replay_id"], reveal_holdout=True)
    assert shown["summary"]["outcomes"]["groups"]["shortlisted"]["3m"]["median_return_pct"] == "50.0"
    assert db.execute("SELECT count(*) FROM audit_log WHERE action = 'HOLDOUT_REVEALED'").fetchone() == (1,)
