"""The weekly triage shortlist against the database.

1. ``build`` reads the combined queue (``inflection.queue``) at the week's cutoff: every company with
   a candidate evaluation public by then, counting only evaluations after its last triage (a triage
   that deferred for budget does not count, so the company keeps its waiting time).  It allocates
   the slots (``rules.allocate``) and stores the shortlist with one item per company, shortlisted
   or not.  One shortlist per week; ``dry_run`` previews without storing.
2. ``show`` prints a week's shortlist; ``record`` stores a triage result on a shortlisted company,
   once, which starts its cooldown.

The cutoff is the end of the week (Sunday midnight IST), or now for the current week, so a past
week can be rebuilt as it would have looked then: evaluations are read by their ``as_of``.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from psycopg.types.json import Jsonb

from .. import queue
from ..asof import IST
from ..queue import LABEL
from . import rules as R

CREATED_BY = "inflection.triage"
ACTIONS = ("DEEP_RESEARCH", "WATCH_MILESTONE", "REJECT_WITH_REASON", "DATA_REPAIR", "DEFER_BUDGET")


def week_bounds(day: date, now: Optional[datetime] = None) -> tuple[date, datetime]:
    """(Monday, cutoff) of the week holding ``day``."""
    start = day - timedelta(days=day.weekday())
    end = datetime.combine(start + timedelta(days=7), time(0), tzinfo=IST)
    now = now or datetime.now(timezone.utc)
    if datetime.combine(start, time(0), tzinfo=IST) > now:
        raise ValueError(f"week of {start} has not started")
    return start, min(end, now)


def _last_triage(conn, cutoff: datetime) -> dict:
    rows = conn.execute(
        """SELECT DISTINCT ON (i.issuer_id) i.issuer_id, s.cutoff, i.priority_class, i.trigger_event_version_ids
             FROM triage_shortlist_items i JOIN triage_shortlists s USING (shortlist_id)
            WHERE i.triage_action IS NOT NULL AND i.triage_action <> 'DEFER_BUDGET' AND s.cutoff < %s
            ORDER BY i.issuer_id, s.cutoff DESC""", (cutoff,)).fetchall()
    return {r[0]: R.Triaged(r[1], r[2], {str(v) for v in r[3]}) for r in rows}


def _public(it: dict, cutoff: datetime) -> dict:
    return dict(position=it["position"], slot=it["slot"], symbol=it["symbol"], name=it["name"],
                priority=it["priority"], corroborated=it["corroborated"],
                waiting_days=(cutoff - it["waiting_since"]).days, stale=it["stale"], reason=it["reason"],
                note=it["note"], triage_action=it.get("triage_action"))


def build(conn, day: date, mode: str = "LIVE", dry_run: bool = False, now: Optional[datetime] = None,
          **overrides) -> dict:
    week_start, cutoff = week_bounds(day, now)
    existing = conn.execute("SELECT shortlist_id FROM triage_shortlists WHERE week_start = %s",
                            (week_start,)).fetchone()
    if existing and not dry_run:
        return dict(show(conn, week_start), existing=True)
    p = R.policy(**overrides)
    last = _last_triage(conn, cutoff)
    lines = queue.lines(conn, None, cutoff, since={k: v.cutoff for k, v in last.items()})
    items = R.allocate(lines, week_start, cutoff, p, last)
    summary = R.summary(items, week_start, cutoff, p)
    out = dict(week_start=week_start.isoformat(), cutoff=cutoff.isoformat(), policy_version=R.POLICY_VERSION,
               policy=p, summary=summary, dry_run=dry_run,
               shortlist=[_public(i, cutoff) for i in items if i["position"] is not None])
    if dry_run:
        return out
    with conn.transaction():
        sid = conn.execute(
            """INSERT INTO triage_shortlists (week_start, cutoff, mode, policy_version, policy, summary, created_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING shortlist_id""",
            (week_start, cutoff, mode, R.POLICY_VERSION, Jsonb(dict(p, hash=R.policy_hash(p))), Jsonb(summary),
             CREATED_BY)).fetchone()[0]
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO triage_shortlist_items
                     (shortlist_id, issuer_id, slot, position, priority_class, corroborated, waiting_since, stale,
                      reason, note, ranking, evaluation_ids, trigger_event_version_ids)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                [(sid, i["issuer_id"], i["slot"], i["position"], i["priority"], i["corroborated"], i["waiting_since"],
                  i["stale"], i["reason"], i["note"], Jsonb(i["ranking"]), i["evaluation_ids"],
                  i["trigger_event_version_ids"]) for i in items])
    out["shortlist_id"] = str(sid)
    return out


def show(conn, day: date, everything: bool = False) -> dict:
    week_start = day - timedelta(days=day.weekday())
    head = conn.execute("""SELECT shortlist_id, cutoff, policy_version, policy, summary FROM triage_shortlists
                            WHERE week_start = %s""", (week_start,)).fetchone()
    if head is None:
        return dict(week_start=week_start.isoformat(), error="no shortlist for this week; run build")
    sid, cutoff, pv, p, summary = head
    rows = conn.execute(
        f"""SELECT i.position, i.slot, {LABEL.format(col='i.issuer_id')}, s.legal_name, i.priority_class,
                   i.corroborated, i.waiting_since, i.stale, i.reason, i.note, i.triage_action
              FROM triage_shortlist_items i JOIN issuers s USING (issuer_id)
             WHERE i.shortlist_id = %s AND (%s OR i.position IS NOT NULL)
             ORDER BY i.position NULLS LAST, i.slot, i.ranking""", (sid, everything)).fetchall()
    items = [dict(position=r[0], slot=r[1], symbol=r[2], name=r[3], priority=r[4], corroborated=r[5],
                  waiting_since=r[6], stale=r[7], reason=r[8], note=r[9], triage_action=r[10]) for r in rows]
    return dict(week_start=week_start.isoformat(), cutoff=cutoff.isoformat(), shortlist_id=str(sid),
                policy_version=pv, policy=p, summary=summary,
                shortlist=[_public(i, cutoff) for i in items])


def record(conn, day: date, symbol: str, action: str, note: Optional[str] = None,
           by: str = "investor", actor_kind: str = "HUMAN") -> dict:
    """Store the triage result for a shortlisted company in that week's shortlist, once."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    week_start = day - timedelta(days=day.weekday())
    row = conn.execute(
        f"""SELECT i.shortlist_id, i.issuer_id, i.slot, i.triage_action, i.revision
              FROM triage_shortlist_items i JOIN triage_shortlists s USING (shortlist_id)
             WHERE s.week_start = %s
               AND upper({LABEL.format(col='i.issuer_id')}) = upper(%s)""", (week_start, symbol)).fetchone()
    if row is None:
        return dict(symbol=symbol, error=f"not in the shortlist for the week of {week_start}")
    sid, issuer_id, slot, done, rev = row
    if slot not in R.SHORTLISTED:
        return dict(symbol=symbol, error=f"in the queue as {slot}, not shortlisted this week")
    if done:
        return dict(symbol=symbol, error=f"already triaged as {done}")
    with conn.transaction():
        n = conn.execute(
            """UPDATE triage_shortlist_items SET triage_action = %s, triage_note = %s, triaged_by = %s,
                      triaged_at = now(), revision = revision + 1
                WHERE shortlist_id = %s AND issuer_id = %s AND revision = %s AND triage_action IS NULL""",
            (action, note, by, sid, issuer_id, rev)).rowcount
        if n != 1:
            return dict(symbol=symbol, error="changed by someone else; read it again")
        conn.execute("""INSERT INTO audit_log (actor, actor_kind, action, target_table, target_id, details)
                        VALUES (%s, %s, 'TRIAGE_RECORDED', 'triage_shortlist_items', %s, %s)""",
                     (by, actor_kind, f"{sid}/{issuer_id}", Jsonb(dict(action=action, note=note, week_start=str(week_start)))))
    return dict(symbol=symbol, week_start=week_start.isoformat(), triage_action=action)
