"""The weekly triage shortlist against the database.

1. ``build`` reads the combined queue (``inflection.queue``) at the week's cutoff: every company with
   a candidate evaluation public by then, counting only assessments not consumed by an earlier completed review. Data-repair and
   budget-deferred outcomes leave their assessments pending.  It allocates
   the slots (``rules.allocate``) and stores the shortlist with one item per company, shortlisted
   or not.  One shortlist per week; ``dry_run`` previews without storing.
2. ``show`` prints a week's shortlist; ``record`` stores a triage result on a shortlisted company,
   once, which starts its cooldown, with the latest packet it was given (``inflection.packets``).

The cutoff is the end of the week (Sunday midnight IST), or now for the current week, so a past
week can be rebuilt as it would have looked then: evaluations are read by their ``as_of``.
"""

from __future__ import annotations

import os
from datetime import date, datetime, time, timedelta, timezone
from typing import Optional

from psycopg.types.json import Jsonb

from .. import queue
from ..asof import IST
from ..queue import LABEL
from . import rules as R
from ..snapshot_lock import snapshot_lock

CREATED_BY = "inflection.triage"


def base_until() -> datetime:
    """A re-run inherits the base run's triage history before this date (INFLECTION_RUN_BASE_UNTIL, the re-run's
    first week), so its first weeks do not treat every company ever queued as never triaged."""
    v = os.environ.get("INFLECTION_RUN_BASE_UNTIL")
    if not v:return datetime(1900,1,1,tzinfo=IST)
    at=datetime.fromisoformat(v)
    return at.replace(tzinfo=IST) if at.tzinfo is None else at.astimezone(IST)


def run_tag() -> str:
    """Which run's shortlists to build and read: 'base' (the original run) unless INFLECTION_RUN_TAG names another."""
    return os.environ.get("INFLECTION_RUN_TAG", "base")
ACTIONS = ("DEEP_RESEARCH", "WATCH_MILESTONE", "REJECT_WITH_REASON", "DATA_REPAIR", "DEFER_BUDGET")


def week_bounds(day: date, now: Optional[datetime] = None) -> tuple[date, datetime]:
    """(Monday, cutoff) of the week holding ``day``."""
    start = day - timedelta(days=day.weekday())
    end = datetime.combine(start + timedelta(days=7), time(0), tzinfo=IST)
    now = now or datetime.now(timezone.utc)
    if datetime.combine(start, time(0), tzinfo=IST) > now:
        raise ValueError(f"week of {start} has not started")
    return start, min(end, now)


def _last_triage(conn, cutoff: datetime, mode: str = "LIVE") -> dict:
    rows = conn.execute(
        """SELECT DISTINCT ON (i.issuer_id) i.issuer_id, s.cutoff, i.priority_class, i.trigger_event_version_ids
             FROM triage_shortlist_items i JOIN triage_shortlists s USING (shortlist_id)
            WHERE i.triage_action IS NOT NULL AND i.triage_action NOT IN ('DEFER_BUDGET','DATA_REPAIR') AND s.cutoff < %s
              AND (s.run_tag = %s OR (s.run_tag = 'base' AND s.cutoff <= %s))
              AND (%s<>'ACTUAL_SYSTEM_REPLAY' OR i.triaged_at<=%s)
            ORDER BY i.issuer_id, s.cutoff DESC""", (cutoff, run_tag(), base_until(),mode,cutoff)).fetchall()
    return {r[0]: R.Triaged(r[1], r[2], {str(v) for v in r[3]}) for r in rows}


def reviewed_evaluations(conn,cutoff: datetime,mode: str='LIVE') -> dict:
    """Assessment identities consumed by eligible reviews, across their full history.

    Use the recorded packet's references when available. A later packet rebuild
    does not change what the earlier decision consumed. Legacy unbound reviews
    fall back to their frozen shortlist references.
    """
    rows=conn.execute("""SELECT i.issuer_id,array_agg(DISTINCT ref)
      FROM triage_shortlist_items i JOIN triage_shortlists s USING(shortlist_id)
      LEFT JOIN triage_packets p ON p.packet_id=i.packet_id AND p.shortlist_id=i.shortlist_id
        AND p.issuer_id=i.issuer_id
      CROSS JOIN LATERAL unnest(CASE
        WHEN jsonb_typeof(p.content->'manifest'->'evaluation_ids')='array'
        THEN ARRAY(SELECT jsonb_array_elements_text(p.content->'manifest'->'evaluation_ids'))
        ELSE i.evaluation_ids::text[] END) ref
      WHERE i.triage_action IS NOT NULL AND i.triage_action NOT IN ('DEFER_BUDGET','DATA_REPAIR')
        AND s.cutoff<%s AND (s.run_tag=%s OR (s.run_tag='base' AND s.cutoff<=%s))
        AND (%s<>'ACTUAL_SYSTEM_REPLAY' OR i.triaged_at<=%s)
      GROUP BY i.issuer_id""",(cutoff,run_tag(),base_until(),mode,cutoff)).fetchall()
    return {issuer:set(ids) for issuer,ids in rows}


def _public(it: dict, cutoff: datetime) -> dict:
    return dict(position=it["position"], slot=it["slot"], symbol=it["symbol"], name=it["name"],
                priority=it["priority"], corroborated=it["corroborated"],
                waiting_days=(cutoff - it["waiting_since"]).days, stale=it["stale"], reason=it["reason"],
                note=it["note"], triage_action=it.get("triage_action"))


def build(conn, day: date, mode: str = "LIVE", dry_run: bool = False, now: Optional[datetime] = None,
          **overrides) -> dict:
    week_start=day-timedelta(days=day.weekday())
    with snapshot_lock(conn,f'triage-shortlist:{run_tag()}:{week_start}'):
        return _build(conn,day,mode,dry_run,now,**overrides)


def _build(conn, day: date, mode: str = 'LIVE',dry_run: bool=False,now: Optional[datetime]=None,**overrides):
    from ..states import RunMode
    mode=RunMode(mode).value
    p=R.policy(**overrides)
    week_start, cutoff = week_bounds(day, now)
    existing = conn.execute("SELECT shortlist_id,cutoff,mode,policy_version,policy FROM triage_shortlists WHERE week_start = %s AND run_tag = %s",
                            (week_start, run_tag())).fetchone()
    if existing and not dry_run:
        sid,stored_cutoff,stored_mode,stored_version,stored_policy=existing
        if stored_mode!=mode or stored_cutoff>cutoff:
            raise ValueError('Stored shortlist has a different mode or a later cutoff; use a separate run tag')
        if any(p[key]!=stored_policy.get(key) for key in overrides):
            raise ValueError('Requested policy differs from the frozen shortlist; use a separate run tag to rebuild')
        return dict(show(conn,week_start),existing=True,requested_cutoff=cutoff.isoformat(),
                    snapshot_behind_requested_cutoff=stored_cutoff<cutoff,
                    snapshot_policy_version_changed=stored_version!=R.POLICY_VERSION)
    last = _last_triage(conn, cutoff,mode)
    lines = queue.lines(conn, None, cutoff, since={k: v.cutoff for k, v in last.items()},mode=mode,
                        reviewed=reviewed_evaluations(conn,cutoff,mode))
    items = R.allocate(lines, week_start, cutoff, p, last)
    summary = R.summary(items, week_start, cutoff, p)
    out = dict(week_start=week_start.isoformat(), cutoff=cutoff.isoformat(), policy_version=R.POLICY_VERSION,
               policy=p, summary=summary, dry_run=dry_run,
               shortlist=[_public(i, cutoff) for i in items if i["position"] is not None])
    if dry_run:
        return out
    with conn.transaction():
        sid = conn.execute(
            """INSERT INTO triage_shortlists (week_start, cutoff, mode, policy_version, policy, summary, created_by, run_tag)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING shortlist_id""",
            (week_start, cutoff, mode, R.POLICY_VERSION, Jsonb(dict(p, hash=R.policy_hash(p))), Jsonb(summary),
             CREATED_BY, run_tag())).fetchone()[0]
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
                            WHERE week_start = %s AND run_tag = %s""", (week_start, run_tag())).fetchone()
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
           by: str = "investor", actor_kind: str = "HUMAN",packet_hash: Optional[str] = None) -> dict:
    """Store the triage result for a shortlisted company in that week's shortlist, once."""
    if action not in ACTIONS:
        raise ValueError(f"action must be one of {ACTIONS}")
    week_start = day - timedelta(days=day.weekday())
    row = conn.execute(
        f"""SELECT i.shortlist_id, i.issuer_id, i.slot, i.triage_action, i.revision
              FROM triage_shortlist_items i JOIN triage_shortlists s USING (shortlist_id)
             WHERE s.week_start = %s AND s.run_tag = %s
               AND upper({LABEL.format(col='i.issuer_id')}) = upper(%s)""", (week_start, run_tag(), symbol)).fetchone()
    if row is None:
        return dict(symbol=symbol, error=f"not in the shortlist for the week of {week_start}")
    sid, issuer_id, slot, done, rev = row
    if slot not in R.SHORTLISTED:
        return dict(symbol=symbol, error=f"in the queue as {slot}, not shortlisted this week")
    if done:
        return dict(symbol=symbol, error=f"already triaged as {done}")
    with conn.transaction():
        from ..packets.pipeline import packet_lock,_latest
        packet_lock(conn,sid,issuer_id)
        latest=_latest(conn,sid,issuer_id)
        if packet_hash is not None and (latest is None or latest[1]!=packet_hash):
            return dict(symbol=symbol,error='Packet changed or hash does not match; read the current packet before recording',
                        latest_packet_id=str(latest[0]) if latest else None)
        if packet_hash is None and conn.execute('SELECT count(*) FROM triage_packets WHERE shortlist_id=%s AND issuer_id=%s',
                                                (sid,issuer_id)).fetchone()[0]>1:
            return dict(symbol=symbol,error='Multiple packet versions exist; supply the hash of the packet reviewed')
        if action=='DEEP_RESEARCH':
            if latest is None or packet_hash is None:
                return dict(symbol=symbol,error='Deep research requires the reviewed packet hash')
            from ..audit import recheck_packet
            checked=recheck_packet(conn,latest[2])
            if checked.get('manifest',{}).get('nomination_issues'):
                return dict(symbol=symbol,error='Nomination packet requires verification before deep research',
                            issues=checked['manifest']['nomination_issues'])
        n = conn.execute(
            """UPDATE triage_shortlist_items SET triage_action = %s, triage_note = %s, triaged_by = %s,
                      triaged_at = now(), revision = revision + 1,
                      packet_id = %s
                WHERE shortlist_id = %s AND issuer_id = %s AND revision = %s AND triage_action IS NULL""",
            (action, note, by, latest[0] if latest else None,sid, issuer_id, rev)).rowcount
        if n != 1:
            return dict(symbol=symbol, error="changed by someone else; read it again")
        conn.execute("""INSERT INTO audit_log (actor, actor_kind, action, target_table, target_id, details)
                        VALUES (%s, %s, 'TRIAGE_RECORDED', 'triage_shortlist_items', %s, %s)""",
                     (by, actor_kind, f"{sid}/{issuer_id}", Jsonb(dict(action=action,note=note,week_start=str(week_start),
                       packet_id=str(latest[0]) if latest else None,packet_hash=latest[1] if latest else None))))
    return dict(symbol=symbol, week_start=week_start.isoformat(), triage_action=action)
