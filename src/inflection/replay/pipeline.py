"""The shadow replay against the database (spec 12, 14 phase 2).

1. ``run`` walks the weeks from ``first`` to ``last``.  Each week it takes the candidate evaluations
   public by the week's cutoff (by ``as_of``; in ACTUAL_SYSTEM_REPLAY also stored by then), builds
   the combined queue (``inflection.queue``) and allocates the shortlist with the live triage rules
   (``inflection.triage.rules``).  Shortlisted companies count as triaged that week, so later weeks
   apply the cooldown and keep waiting times exactly as the live shortlist would.  Nothing is
   written to the live tables: no shortlist, packet, case or decision.
2. For every shortlisted company, and every company with new evidence that week that was not
   shortlisted, it measures the later price outcome at each horizon (``rules.outcome``) against the
   median of the same exchange's universe over the same dates.
3. It lists large later price moves, quarter by quarter, and whether the replay had shortlisted the
   company in time (``rules.winner_status``): the missed winners.
4. It reports coverage week by week: announcements, results filings, evaluations by route and price
   days, so a week the commercial route could not see is visible rather than read as "nothing found".

Evaluations were computed after the fact from filings with proven publication times, so the
default mode is PUBLIC_INFORMATION_RECONSTRUCTION.  ``report``, ``weeks`` and ``winners`` read a
stored replay back.
"""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Optional

from psycopg.types.json import Jsonb

from .. import queue
from ..asof import IST
from ..financials import SOURCE as XBRL_SOURCE
from ..triage import rules as TR
from . import rules as R

CREATED_BY = "inflection.replay"
MODES = ("PUBLIC_INFORMATION_RECONSTRUCTION", "ACTUAL_SYSTEM_REPLAY")
ANNOUNCEMENT_SOURCES = ("nse_announcements", "bse_announcements")
PROVIDER_ORDER = ("nse_bhavcopy", "bse_bhavcopy")


# ---------------------------------------------------------------- weekly queue

def _queue_weeks(rows: list[tuple], weeks: list[tuple[date, datetime]], mode: str, tp: dict,
                 holdout_from: Optional[date]) -> tuple[list[dict], list[dict]]:
    """(week rows, item rows).  Items are the shortlisted companies and the companies with new
    evidence that week that were not shortlisted."""
    last: dict = {}
    week_rows, kept = [], []
    for week_start, cutoff in weeks:
        visible = [r for r in rows if r[4] < cutoff and (mode != "ACTUAL_SYSTEM_REPLAY" or r[14] <= cutoff)]
        lines = queue.from_rows(visible, since={k: v.cutoff for k, v in last.items()})
        items = TR.allocate(lines, week_start, cutoff, tp, last)
        start = datetime.combine(week_start, datetime.min.time(), tzinfo=IST)
        per = R.period(week_start, holdout_from)
        for it in items:
            shortlisted = it["slot"] in TR.SHORTLISTED
            if shortlisted:
                last[it["issuer_id"]] = TR.Triaged(cutoff, it["priority"], set(it["trigger_event_version_ids"]))
            if shortlisted or it["latest"] >= start:
                kept.append(dict(week_start=week_start, cutoff=cutoff, period=per, issuer_id=it["issuer_id"],
                                 symbol=it["symbol"], slot=it["slot"], position=it["position"],
                                 shortlisted=shortlisted, priority_class=it["priority"], routes=it["routes"],
                                 corroborated=it["corroborated"], waiting_since=it["waiting_since"],
                                 reason=it["reason"], evaluation_ids=it["evaluation_ids"]))
        routes = Counter(r[3] for r in visible if r[4] >= start)
        week_rows.append(dict(week_start=week_start, cutoff=cutoff, period=per,
                              queue=TR.summary(items, week_start, cutoff, tp),
                              evaluations=dict(sorted(routes.items()))))
    R.mark_first_time(kept)
    return week_rows, kept


# ---------------------------------------------------------------- coverage

def _weekly_counts(conn, sql: str, params: dict) -> dict:
    return {r[0]: r[1] for r in conn.execute(sql, params).fetchall()}


def _coverage(conn, first: date, last: date, mode: str = 'PUBLIC_INFORMATION_RECONSTRUCTION') -> dict:
    """Counts per Monday: announcements, results filings and price days by exchange."""
    lo = datetime.combine(first, datetime.min.time(), tzinfo=IST)
    hi = datetime.combine(last + timedelta(days=7), datetime.min.time(), tzinfo=IST)
    week = "date_trunc('week', coalesce(p.published_at AT TIME ZONE 'Asia/Kolkata', p.published_date::timestamp))::date"
    pubs = f"""SELECT {week}, count(*) FROM document_publications p JOIN sources s USING (source_id)
                WHERE s.name = ANY(%(names)s)
                  AND coalesce(p.published_at, p.published_date::timestamp AT TIME ZONE 'Asia/Kolkata') >= %(lo)s
                  AND coalesce(p.published_at, p.published_date::timestamp AT TIME ZONE 'Asia/Kolkata') < %(hi)s
                  AND (%(actual)s=false OR p.ingested_at < (({week}+7)::timestamp AT TIME ZONE 'Asia/Kolkata'))
                GROUP BY 1"""
    out = dict(
        announcements=_weekly_counts(conn, pubs, dict(names=list(ANNOUNCEMENT_SOURCES), lo=lo, hi=hi, actual=mode=='ACTUAL_SYSTEM_REPLAY')),
        results_filings=_weekly_counts(conn, pubs, dict(names=[XBRL_SOURCE], lo=lo, hi=hi, actual=mode=='ACTUAL_SYSTEM_REPLAY')))
    for provider in PROVIDER_ORDER:
        out[f"{provider}_days"] = _weekly_counts(
            conn, """SELECT date_trunc('week', trade_date)::date, count(DISTINCT trade_date) FROM prices
                      WHERE provider = %(p)s AND adjustment = 'UNADJUSTED' AND trade_date BETWEEN %(a)s AND %(b)s
                      GROUP BY 1""", dict(p=provider, a=first, b=last + timedelta(days=6)))
    return out


def _coverage_summary(week_rows: list[dict], rows: list[tuple]) -> dict:
    n = len(week_rows)
    blind = [w["week_start"] for w in week_rows if not w["coverage"]["announcements"]]
    no_results = [w["week_start"] for w in week_rows if not w["coverage"]["results_filings"]]
    ann = [w["week_start"] for w in week_rows if w["coverage"]["announcements"]]
    warnings = []
    if blind:
        warnings.append(f"no announcements in {len(blind)} of {n} weeks: the commercial route could not see "
                        "those weeks; read their results as financial route only")
    u0 = sum(1 for r in rows if r[5] == "U0")
    if u0:
        warnings.append(f"{u0} evaluations are U0, set from research cases open when the route ran, not when "
                        "the filing was public")
    return dict(
        weeks=n, weeks_with_announcements=n - len(blind), weeks_with_results_filings=n - len(no_results),
        first_announcement_week=ann[0].isoformat() if ann else None,
        last_announcement_week=ann[-1].isoformat() if ann else None,
        announcements=sum(w["coverage"]["announcements"] for w in week_rows),
        results_filings=sum(w["coverage"]["results_filings"] for w in week_rows),
        evaluations=dict(Counter(r[3] for r in rows)),
        warnings=warnings)


# ---------------------------------------------------------------- prices

class Prices:
    """Closes and corporate actions per security, read once; the universe median per date pair."""

    def __init__(self, conn):
        self.conn = conn
        self.series: dict = {}
        self.actions: dict = {}
        self.bench: dict = {}
        self.benchmark_coverage: dict = {}
        self.last_day = dict(conn.execute(
            "SELECT provider, max(trade_date) FROM prices WHERE adjustment = 'UNADJUSTED' GROUP BY 1").fetchall())

    def candidates(self, issuer_id) -> list[tuple]:
        rows = self.conn.execute(
            """SELECT DISTINCT p.security_id, p.provider FROM prices p JOIN securities s USING (security_id)
                WHERE s.issuer_id = %s AND p.adjustment = 'UNADJUSTED'""", (issuer_id,)).fetchall()
        return sorted(rows, key=lambda r: (PROVIDER_ORDER.index(r[1]) if r[1] in PROVIDER_ORDER else 9, str(r[0])))

    def closes(self, security_id, provider, start: Optional[date] = None, end: Optional[date] = None) -> list[tuple]:
        """(trade date, close) in [start, end], sorted."""
        key = (security_id, provider)
        if key not in self.series:
            rows = self.conn.execute(
                """SELECT trade_date, close FROM prices WHERE security_id = %s AND provider = %s
                      AND adjustment = 'UNADJUSTED' AND close > 0 ORDER BY trade_date""", key).fetchall()
            self.series[key] = ([d for d, _ in rows], rows)
        dates, rows = self.series[key]
        lo = bisect_left(dates, start) if start else 0
        hi = bisect_right(dates, end) if end else len(rows)
        return rows[lo:hi]

    def corporate_actions(self, security_id) -> list[dict]:
        if security_id not in self.actions:
            self.actions[security_id] = [
                dict(kind=k, ex_date=d, multiplier=Decimal(m) if m is not None else None, reconciled=ok)
                for k, d, m, ok in self.conn.execute(
                    """SELECT kind, ex_date, details->>'price_multiplier', reconciled FROM corporate_actions
                        WHERE security_id = %s ORDER BY ex_date""", (security_id,)).fetchall()]
        return self.actions[security_id]

    def pick(self, issuer_id, target: date, p: dict) -> Optional[tuple]:
        """The security and exchange to measure: NSE first, the first with a close near the entry."""
        for sec, provider in self.candidates(issuer_id):
            if self.closes(sec, provider, target, target + timedelta(days=p["entry_window_days"])):
                return sec, provider
        return None

    def benchmark(self, provider: str, d1: date, d2: date) -> tuple[Optional[Decimal], int]:
        key = (provider, d1, d2)
        if key not in self.bench:
            median_, measured, entered, missing, invalid = self.conn.execute(_UNIVERSE + """
                SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY r) FILTER (WHERE NOT bad),
                       count(*) FILTER (WHERE NOT bad), count(*), count(*) FILTER (WHERE c2 IS NULL),
                       count(*) FILTER (WHERE bad AND c2 IS NOT NULL) FROM j""",
                dict(p=provider, d1=d1, d2=d2)).fetchone()
            self.bench[key] = (median_, measured)
            self.benchmark_coverage[key] = dict(entry_securities=entered, measured=measured,
                                               missing_exit=missing, uncertain_actions=invalid)
        m, n = self.bench[key]
        return (Decimal(str(m)).quantize(R.TWO) if m is not None else None), n


# Every security of one exchange with a close on both days: its split/bonus-adjusted price return,
# and ``bad`` when a split or bonus in between has no multiplier or is not reconciled.
_UNIVERSE = """
WITH a AS (SELECT DISTINCT ON (security_id) security_id, close FROM prices
            WHERE provider = %(p)s AND adjustment = 'UNADJUSTED' AND trade_date = %(d1)s AND close > 0
            ORDER BY security_id, recorded_at DESC, provider_version DESC),
     b AS (SELECT DISTINCT ON (security_id) security_id, close FROM prices
            WHERE provider = %(p)s AND adjustment = 'UNADJUSTED' AND trade_date = %(d2)s AND close > 0
            ORDER BY security_id, recorded_at DESC, provider_version DESC),
     j AS (SELECT a.security_id, a.close AS c1, b.close AS c2,
                  b.close / (a.close * coalesce(f.m, 1)) - 1 AS r,
                  b.close IS NULL OR coalesce(f.bad, false) AS bad
             FROM a LEFT JOIN b USING (security_id)
             LEFT JOIN LATERAL (
                  SELECT exp(sum(CASE WHEN x.kind IN ('SPLIT','BONUS') AND
                         (x.details->>'price_multiplier')::numeric > 0
                         THEN ln((x.details->>'price_multiplier')::numeric) END)) AS m,
                         bool_or(x.kind IN ('RIGHTS','MERGER','DELISTING','DEMERGER') OR
                             (x.kind IN ('SPLIT','BONUS') AND (NOT x.reconciled OR
                              coalesce((x.details->>'price_multiplier')::numeric,0) <= 0))) AS bad
                    FROM corporate_actions x
                   WHERE x.security_id = a.security_id AND x.kind IN ('SPLIT','BONUS','RIGHTS','MERGER','DELISTING','DEMERGER')
                     AND x.ex_date > %(d1)s AND x.ex_date <= %(d2)s) f ON true)"""


def _session(conn, provider: str, target: date, after: bool) -> Optional[date]:
    op, order = (">=", "ASC") if after else ("<=", "DESC")
    row = conn.execute(f"""SELECT trade_date FROM prices WHERE provider = %s AND adjustment = 'UNADJUSTED'
                             AND trade_date {op} %s ORDER BY trade_date {order} LIMIT 1""",
                       (provider, target)).fetchone()
    return row[0] if row else None


def _outcomes(px: Prices, items: list[dict], p: dict) -> list[dict]:
    out = []
    for it in items:
        target = R.entry_target(it["cutoff"], p)
        picked = px.pick(it["issuer_id"], target, p)
        for h, days in p["horizons"].items():
            base = dict(week_start=it["week_start"], issuer_id=it["issuer_id"], horizon=h)
            if picked is None:
                out.append(dict(base, status="NO_PRICE", security_id=None, provider=None, notes=[
                    f"no security of the company has a close within {p['entry_window_days']} days of "
                    f"{target.isoformat()}"]))
                continue
            sec, provider = picked
            series = px.closes(sec, provider, target, target + timedelta(days=p["entry_window_days"] + days))
            o = R.outcome(series, px.corporate_actions(sec), target, days, px.last_day[provider], p)
            row = dict(base, status=o.status, security_id=sec, provider=provider, entry_date=o.entry_date,
                       entry_close=o.entry_close, exit_date=o.exit_date, exit_close=o.exit_close,
                       price_multiplier=o.multiplier, price_return=o.price_return, max_drawdown=o.max_drawdown,
                       notes=o.notes)
            if o.price_return is not None:
                bm, n = px.benchmark(provider, o.entry_date, o.exit_date)
                row.update(benchmark_return=bm, benchmark_count=n,
                           excess_return=(o.price_return - bm) if bm is not None else None)
                quality = px.benchmark_coverage[(provider, o.entry_date, o.exit_date)]
                if quality['missing_exit'] or quality['uncertain_actions']:
                    row['notes'].append(f"benchmark coverage: {quality['measured']}/{quality['entry_securities']} entry securities; "
                                        f"{quality['missing_exit']} missing exits, {quality['uncertain_actions']} uncertain actions; "
                                        "survivorship risk remains")
            out.append(row)
    return out


# ---------------------------------------------------------------- missed winners

def _winners(conn, px: Prices, items: list[dict], all_lines: dict, first: date, last: date, p: dict,
             mode: str = 'PUBLIC_INFORMATION_RECONSTRUCTION') -> list[dict]:
    """Large price moves over the big-move horizon starting each quarter in the interval."""
    days = p["horizons"][p["big_move_horizon"]]
    short = defaultdict(list)
    for it in items:
        if it["shortlisted"]:
            short[it["issuer_id"]].append(it["week_start"])
    out, seen = [], set()
    q = date(first.year, 3 * ((first.month - 1) // 3) + 1, 1)
    while q <= last:
        for provider in PROVIDER_ORDER:
            last_day = px.last_day.get(provider)
            d1 = _session(conn, provider, q, after=True)
            if last_day is None or d1 is None or d1 + timedelta(days=days) > last_day:
                continue
            d2 = _session(conn, provider, d1 + timedelta(days=days), after=False)
            rows = conn.execute(
                _UNIVERSE + """
                SELECT j.security_id, s.issuer_id, j.r FROM j JOIN securities s USING (security_id)
                 WHERE NOT j.bad AND j.r >= %(big)s
                   AND (SELECT avg(x.close * x.volume) FROM prices x
                         WHERE x.security_id = j.security_id AND x.provider = %(p)s AND x.adjustment = 'UNADJUSTED'
                           AND x.trade_date BETWEEN %(d1)s::date - 30 AND %(d1)s) >= %(liq)s""",
                dict(p=provider, d1=d1, d2=d2, big=Decimal(p["big_move"]),
                     liq=Decimal(p["winner_min_traded_value"]))).fetchall()
            for sec, issuer, r in rows:
                if (issuer, q) in seen:
                    continue                       # the same company on both exchanges
                seen.add((issuer, q))
                lo = d1 - timedelta(days=p["winner_lookback_days"])
                hi = d1 + timedelta(days=p["winner_lookahead_days"])
                figures, filings = conn.execute(
                    """SELECT EXISTS (SELECT 1 FROM financial_facts_asof WHERE issuer_id = %(i)s
                                         AND available_at BETWEEN %(lo)s AND %(hi)s
                                         AND (%(actual)s=false OR recorded_at<=%(hi)s)),
                              EXISTS (SELECT 1 FROM document_publications p JOIN sources s USING (source_id)
                                       WHERE p.issuer_id = %(i)s AND s.name = ANY(%(names)s)
                                         AND coalesce(p.published_at, p.published_date::timestamp
                                                      AT TIME ZONE 'Asia/Kolkata') BETWEEN %(lo)s AND %(hi)s
                                         AND (%(actual)s=false OR p.ingested_at<=%(hi)s))""",
                    dict(i=issuer, lo=datetime.combine(lo, datetime.min.time(), tzinfo=IST),
                         hi=datetime.combine(hi, datetime.min.time(), tzinfo=IST),
                         names=list(ANNOUNCEMENT_SOURCES),actual=mode=='ACTUAL_SYSTEM_REPLAY')).fetchone()
                status, when = R.winner_status(short.get(issuer, []), all_lines.get(issuer, []), figures, filings,
                                               d1, p)
                out.append(dict(window_start=q, security_id=sec, issuer_id=issuer, provider=provider, entry_date=d1,
                                exit_date=d2, price_return=Decimal(str(r)).quantize(R.TWO), status=status,
                                first_shortlisted=when, detail=dict(results_figures_before=figures,
                                                                    announcements_before=filings)))
        q = date(q.year + (q.month + 2) // 12, (q.month + 2) % 12 + 1, 1)
    return out


def _winner_summary(winners: list[dict]) -> dict:
    by = Counter(w["status"] for w in winners)
    n = len(winners)
    return dict(big_moves=n, by_status=dict(sorted(by.items())),
                shortlisted_in_time_pct=str(round(100 * by["SHORTLISTED"] / n, 1)) if n else None,
                note="a big move is a price event, not proof of an earnings inflection; read the misses for "
                     "coverage gaps and rules that did not fire, not as a recall score")


# ---------------------------------------------------------------- run

def run(conn, first: date, last: date, mode: str = "PUBLIC_INFORMATION_RECONSTRUCTION",
        holdout_from: Optional[date] = None, dry_run: bool = False, now: Optional[datetime] = None,
        triage: Optional[dict] = None, **overrides) -> dict:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    p = R.policy(**overrides)
    tp = TR.policy(**(triage or {}))
    now = now or datetime.now(timezone.utc)
    weeks = [(w, c) for w, c in R.weeks(first, last) if c <= now]
    if not weeks:
        raise ValueError("no complete week in the interval")
    rows = queue.evaluation_rows(conn, None, weeks[-1][1], include_superseded=mode == "ACTUAL_SYSTEM_REPLAY")
    week_rows, items = _queue_weeks(rows, weeks, mode, tp, holdout_from)
    cov = _coverage(conn, weeks[0][0], weeks[-1][0], mode)
    for w in week_rows:
        w["coverage"] = dict(evaluations=w.pop("evaluations"),
                             **{k: v.get(w["week_start"], 0) for k, v in cov.items()})
    px = Prices(conn)
    outcomes = _outcomes(px, items, p)
    queued = defaultdict(list)
    for i in items:
        queued[i["issuer_id"]].append(i["week_start"])
    winners = _winners(conn, px, items, queued, weeks[0][0], weeks[-1][0], p, mode)
    coverage = _coverage_summary(week_rows, [r for r in rows if r[4] < weeks[-1][1]])
    coverage["prices_last_day"] = {k: v.isoformat() for k, v in px.last_day.items()}
    summary = dict(
        weeks=len(week_rows), shortlisted=sum(1 for i in items if i["shortlisted"]),
        shortlisted_companies=len({i["issuer_id"] for i in items if i["shortlisted"]}),
        comparison_items=sum(1 for i in items if not i["shortlisted"]),
        outcomes=R.summarise(items, outcomes, p), winners=_winner_summary(winners))
    out = dict(mode=mode, first_week=weeks[0][0].isoformat(), last_week=weeks[-1][0].isoformat(),
               holdout_from=holdout_from.isoformat() if holdout_from else None, policy_version=R.POLICY_VERSION,
               policy=p, triage_policy=tp, coverage=coverage, summary=summary, dry_run=dry_run)
    if dry_run:
        return out
    with conn.transaction():
        rid = conn.execute(
            """INSERT INTO shadow_replays (mode, first_week, last_week, holdout_from, policy_version, policy,
                                           triage_policy, coverage, summary, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING replay_id""",
            (mode, weeks[0][0], weeks[-1][0], holdout_from, R.POLICY_VERSION,
             Jsonb(dict(p, hash=R.policy_hash(p))), Jsonb(dict(tp, version=TR.POLICY_VERSION, hash=TR.policy_hash(tp))),
             Jsonb(coverage), Jsonb(summary, dumps=_dumps), CREATED_BY)).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO shadow_replay_weeks (replay_id, week_start, cutoff, period, queue, coverage)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                [(rid, w["week_start"], w["cutoff"], w["period"], Jsonb(w["queue"]), Jsonb(w["coverage"]))
                 for w in week_rows])
            cur.executemany(
                """INSERT INTO shadow_replay_items (replay_id, week_start, issuer_id, slot, position, shortlisted,
                                                    priority_class, routes, corroborated, waiting_since, reason,
                                                    evaluation_ids)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [(rid, i["week_start"], i["issuer_id"], i["slot"], i["position"], i["shortlisted"],
                  i["priority_class"], i["routes"], i["corroborated"], i["waiting_since"], i["reason"],
                  i["evaluation_ids"]) for i in items])
            cur.executemany(
                """INSERT INTO outcomes.shadow_replay_outcomes (replay_id, week_start, issuer_id, horizon, status, security_id,
                                                       provider, entry_date, entry_close, exit_date, exit_close,
                                                       price_multiplier, price_return, benchmark_return,
                                                       benchmark_count, excess_return, max_drawdown, notes)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [(rid, o["week_start"], o["issuer_id"], o["horizon"], o["status"], o.get("security_id"),
                  o.get("provider"), o.get("entry_date"), o.get("entry_close"), o.get("exit_date"),
                  o.get("exit_close"), o.get("price_multiplier"), o.get("price_return"), o.get("benchmark_return"),
                  o.get("benchmark_count"), o.get("excess_return"), o.get("max_drawdown"), o.get("notes", []))
                 for o in outcomes])
            cur.executemany(
                """INSERT INTO outcomes.shadow_replay_winners (replay_id, window_start, security_id, issuer_id, provider,
                                                      entry_date, exit_date, price_return, status, first_shortlisted,
                                                      detail)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [(rid, w["window_start"], w["security_id"], w["issuer_id"], w["provider"], w["entry_date"],
                  w["exit_date"], w["price_return"], w["status"], w["first_shortlisted"], Jsonb(w["detail"]))
                 for w in winners])
    out["replay_id"] = str(rid)
    return out


def _dumps(obj) -> str:
    import json
    return json.dumps(obj, default=str)


# ---------------------------------------------------------------- reading back

def _replay(conn, replay_id: Optional[str]):
    sql = """SELECT replay_id, mode, first_week, last_week, holdout_from, policy, triage_policy, coverage, summary,
                    created_at FROM shadow_replays"""
    row = conn.execute(sql + (" WHERE replay_id = %s" if replay_id else " ORDER BY created_at DESC LIMIT 1"),
                       (replay_id,) if replay_id else ()).fetchone()
    return row


def report(conn, replay_id: Optional[str] = None, reveal_holdout: bool = False, by: str = "investor") -> dict:
    """The stored summary; ``reveal_holdout`` recomputes it with the holdout weeks' returns, and logs it."""
    row = _replay(conn, replay_id)
    if row is None:
        return dict(error="no shadow replay stored; run one first")
    rid, mode, fw, lw, hf, p, tp, cov, summary, created = row
    out = dict(replay_id=str(rid), mode=mode, first_week=fw.isoformat(), last_week=lw.isoformat(),
               holdout_from=hf.isoformat() if hf else None, created_at=created.isoformat(), policy=p,
               triage_policy=tp, coverage=cov, summary=summary)
    if reveal_holdout and hf:
        items = [dict(week_start=w, issuer_id=i, slot=s, shortlisted=sh, priority_class=c, routes=r, period=per)
                 for w, i, s, sh, c, r, per in conn.execute(
                     """SELECT i.week_start, i.issuer_id, i.slot, i.shortlisted, i.priority_class, i.routes, w.period
                          FROM shadow_replay_items i JOIN shadow_replay_weeks w USING (replay_id, week_start)
                         WHERE i.replay_id = %s""", (rid,)).fetchall()]
        R.mark_first_time(items)
        outcomes = [dict(week_start=w, issuer_id=i, horizon=h, status=s, price_return=r, excess_return=e,
                         max_drawdown=d)
                    for w, i, h, s, r, e, d in conn.execute(
                        """SELECT week_start, issuer_id, horizon, status, price_return, excess_return, max_drawdown
                             FROM outcomes.shadow_replay_outcomes WHERE replay_id = %s""", (rid,)).fetchall()]
        out["summary"] = dict(summary, outcomes=R.summarise(items, outcomes, {**R.POLICY, **p}, include_holdout=True))
        conn.execute("""INSERT INTO audit_log (actor, actor_kind, action, target_table, target_id, details)
                        VALUES (%s, 'HUMAN', 'HOLDOUT_REVEALED', 'shadow_replays', %s, %s)""",
                     (by, str(rid), Jsonb(dict(holdout_from=hf.isoformat()))))
    return out


def weeks(conn, replay_id: Optional[str] = None) -> list[dict]:
    row = _replay(conn, replay_id)
    if row is None:
        return []
    rows = conn.execute(
        """SELECT week_start, period, queue, coverage FROM shadow_replay_weeks WHERE replay_id = %s
            ORDER BY week_start""", (row[0],)).fetchall()
    return [dict(week_start=w.isoformat(), period=per, shortlisted=q.get("shortlisted"),
                 in_queue=q.get("companies_in_queue"), new=q.get("new_this_week"), stale=q.get("stale"),
                 slots=q.get("slots"), coverage=c) for w, per, q, c in rows]


def winners(conn, replay_id: Optional[str] = None, status: Optional[str] = None, top: int = 50) -> list[dict]:
    row = _replay(conn, replay_id)
    if row is None:
        return []
    rows = conn.execute(
        f"""SELECT w.window_start, {queue.LABEL.format(col='w.issuer_id')}, i.legal_name, w.provider, w.entry_date,
                   w.exit_date, w.price_return, w.status, w.first_shortlisted, w.detail
              FROM outcomes.shadow_replay_winners w JOIN issuers i USING (issuer_id)
             WHERE w.replay_id = %s AND (%s::text IS NULL OR w.status = %s)
             ORDER BY w.window_start, w.price_return DESC LIMIT %s""", (row[0], status, status, top)).fetchall()
    return [dict(window_start=a.isoformat(), symbol=b, name=c, exchange=d, entry=e.isoformat(), exit=f.isoformat(),
                 return_pct=str((g * 100).quantize(Decimal("0.1"))), status=h,
                 first_shortlisted=k.isoformat() if k else None, **detail)
            for a, b, c, d, e, f, g, h, k, detail in rows]
