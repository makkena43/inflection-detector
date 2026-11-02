"""Reprocess audited source documents and append corrected historical packets.

No downloads, model calls, investment decisions or historical-review mutations.
Run with --sample pointing to an audit's JSON list containing packet_id fields.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import psycopg
from psycopg.types.json import Jsonb

from .commercial import pipeline as commercial, vocabulary as V
from .packets import pipeline as packets, contents as C
from .commercial.readings import ready_sql


def source_artifacts(content):
    return sorted({p['text_artifact_id'] for key in ('trigger_passages', 'contradicting_passages')
                   for p in content.get(key, []) if p.get('text_artifact_id')}
                  | {d['text_artifact_id'] for d in content.get('documents', []) if d.get('text_artifact_id')})


def refresh_packet(conn, packet_id):
    head=conn.execute('SELECT shortlist_id,issuer_id FROM triage_packets WHERE packet_id=%s',(packet_id,)).fetchone()
    if head is None:raise ValueError(f'Unknown packet: {packet_id}')
    with packets.packet_snapshot(conn,*head):
        return _refresh_packet(conn,packet_id)


def _refresh_packet(conn, packet_id):
    """Rebuild from current readings of the original sources, at the original cutoff.

    Retain original shortlist allocation and signed/model review history. A new
    packet replaces obsolete source interpretations in subsequent packet reads.
    """
    with conn.transaction():
        row = conn.execute('''SELECT p.shortlist_id,p.issuer_id,p.cutoff,p.mode,p.content,p.token_budget,
                s.week_start,s.policy_version,s.policy->>'hash',i.slot,i.position,i.priority_class,
                i.corroborated,i.waiting_since,i.stale,i.reason,i.note,i.evaluation_ids
            FROM triage_packets p JOIN triage_shortlists s USING(shortlist_id)
            JOIN triage_shortlist_items i ON i.shortlist_id=p.shortlist_id AND i.issuer_id=p.issuer_id
            WHERE p.packet_id=%s''', (packet_id,)).fetchone()
        if row is None:
            raise ValueError(f'Unknown packet: {packet_id}')
        sid, issuer, cutoff, mode, original, budget = row[:6]
        if mode=='ACTUAL_SYSTEM_REPLAY':
            raise ValueError('Actual-system packets remain frozen; use a separate reconstruction run')
        packets.packet_lock(conn,sid,issuer)
        tids = source_artifacts(original)
        # Old commercial evaluations disappear only after their exact source has
        # been reread successfully. Other routes remain original cutoff context.
        evaluations = conn.execute('''SELECT evaluation_id,route,
              components->'filing'->>'text_artifact_id' FROM candidate_evaluations
              WHERE evaluation_id=ANY(%s::uuid[]) AND as_of<=%s AND issuer_id=%s''', (row[17], cutoff,issuer)).fetchall()
        reread = {str(t) for (t,) in conn.execute(f'''SELECT text_artifact_id FROM commercial_scans cs
             WHERE rules_version=%s AND text_artifact_id=ANY(%s::uuid[]) AND issuer_id=%s
               AND {ready_sql('cs')}''', (V.RULES_VERSION, tids,issuer))}
        retained = [eid for eid, route, tid in evaluations if route != 'COMMERCIAL' or tid not in reread]
        current = conn.execute('''SELECT evaluation_id FROM candidate_evaluations
             WHERE issuer_id=%s AND route='COMMERCIAL' AND policy_version=%s AND as_of<=%s
               AND components->'filing'->>'text_artifact_id'=ANY(%s::text[])''',
             (issuer, V.RULES_VERSION, cutoff, tids)).fetchall()
        retained.extend(eid for (eid,) in current)
        # Evidence from the same audited sources, not every company event or a
        # future quarter. packet_for applies the publication and replay guards.
        versions = conn.execute('''SELECT DISTINCT v.event_version_id FROM event_versions v
              JOIN events e USING(event_id) JOIN evidence_links l USING(event_version_id)
             WHERE e.issuer_id=%s AND e.rules_version=%s
               AND l.text_artifact_id=ANY(%s::uuid[]) AND l.relation='SUPPORTS'
               AND v.published_at<=%s''', (issuer, V.RULES_VERSION, tids, cutoff)).fetchall()
        # A source without a current reading remains an explicit processing gap.
        old_events = [e.get('version_id') for e in original.get('events', []) if e.get('version_id')]
        if tids and len(reread) != len(tids):
            raise ValueError(f'Cannot refresh packet until all source artifacts are reread: {len(reread)}/{len(tids)}')
        it = dict(shortlist_id=sid, issuer_id=issuer, cutoff=cutoff, mode=mode,
                  week_start=row[6], policy_version=row[7], policy_hash=row[8], slot=row[9],
                  position=row[10], priority=row[11], corroborated=row[12], waiting_since=row[13],
                  stale=row[14], reason='Source evidence refreshed; reassess the original nomination', note=row[16],
                  evaluation_ids=list(dict.fromkeys(retained)),
                  trigger_event_version_ids=[v for (v,) in versions] if tids else old_events,
                  label=original['company']['label'], name=original['company']['name'],
                  has_symbol=bool(original['company'].get('symbols')))
        content, md = packets.packet_for(conn, it, budget)
        if any(e.get('details',{}).get('history_conflict') for e in content.get('events',[])):
            raise ValueError('Chronological source history still requires rebuilding')
        content['manifest']['repair'] = dict(version='audit-repair-1', original_packet_id=str(packet_id),
                                              commercial_rules=V.RULES_VERSION,
                                              original_evaluation_ids=[str(e) for e in row[17]])
        # Deterministic metadata makes repeated repairs idempotent.
        md = C.render(content)
        content['manifest']['token_estimate'] = C.estimate_tokens(md)
        stored=packets.store_packet(conn,it,content,budget,created_by='inflection.audit_repair')
        pid=stored['packet_id']
        if stored['status']=='UNCHANGED':
            return dict(original_packet_id=str(packet_id),packet_id=str(pid),status='UNCHANGED')
        details = dict(original_packet_id=str(packet_id), packet_id=str(pid), rules_version=V.RULES_VERSION,
                       source_artifacts=len(tids), source_event_versions=len(versions))
        conn.execute('''INSERT INTO audit_log(actor,actor_kind,action,target_table,target_id,details)
             VALUES('inflection.audit_repair','SYSTEM','REFRESH_SOURCE_PACKET','triage_packets',%s,%s)''',
             (str(pid),Jsonb(details)))
        return details | dict(status='REFRESHED')


def run(conn, packet_ids):
    ids = sorted(set(str(p) for p in packet_ids))
    tids = set()
    for pid in ids:
        row = conn.execute('SELECT content FROM triage_packets WHERE packet_id=%s', (pid,)).fetchone()
        if not row:
            raise ValueError(f'Unknown packet: {pid}')
        tids.update(source_artifacts(row[0]))
    # Coordinate with the repair worker, so overlapping scans/resolutions cannot
    # create duplicate versions while the sampled evidence is being refreshed.
    conn.execute('SELECT pg_advisory_lock(20261029,101)')
    try:
        scanned = commercial.scan(conn, artifact_ids=sorted(tids))
        resolved = commercial.resolve(conn, artifact_ids=sorted(tids))
        repaired = [refresh_packet(conn, pid) for pid in ids]
    finally:
        conn.execute('SELECT pg_advisory_unlock(20261029,101)')
    return dict(rules_version=V.RULES_VERSION, source_artifacts=len(tids),
                scanned=dict(scanned), resolved=dict(resolved), packets=repaired)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--sample', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args(argv)
    sample = json.loads(args.sample.read_text())
    with psycopg.connect(os.environ.get('INFLECTION_DSN','postgresql:///inflection'), autocommit=True) as conn:
        report = run(conn, [r['packet_id'] for r in sample])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, default=str)+'\n')
    print(json.dumps(dict(source_artifacts=report['source_artifacts'],scanned=report['scanned'],
                          resolved=report['resolved'],packets=len(report['packets']))))



def history_conflict_packets(conn,start,end):
    """Latest non-actual packets whose effective source history needs rebuilding."""
    from datetime import datetime,time,timedelta
    from .asof import IST
    from .temporal import future_event_parent_sql
    lo=datetime.combine(start,time.min,IST);hi=datetime.combine(end+timedelta(days=1),time.min,IST)
    return [r[0] for r in conn.execute(f"""WITH affected AS (
        SELECT DISTINCT child.event_id,e.issuer_id FROM event_versions child
        JOIN event_versions later ON later.event_id=child.event_id
          AND later.version_no>child.version_no AND later.published_at<child.published_at
        JOIN events e ON e.event_id=child.event_id
        UNION
        SELECT DISTINCT child.event_id,e.issuer_id FROM event_versions child
        JOIN event_versions parent ON parent.event_version_id=child.supersedes_id
          AND parent.published_at>child.published_at
        JOIN events e ON e.event_id=child.event_id),
      latest AS (SELECT DISTINCT ON(p.shortlist_id,p.issuer_id) p.packet_id,p.content,p.cutoff
        FROM triage_packets p WHERE p.mode<>'ACTUAL_SYSTEM_REPLAY' AND p.cutoff>=%s AND p.cutoff<%s
          AND p.issuer_id IN(SELECT issuer_id FROM affected)
        ORDER BY p.shortlist_id,p.issuer_id,p.created_at DESC,p.packet_id DESC)
      SELECT DISTINCT p.packet_id FROM latest p
        CROSS JOIN LATERAL jsonb_array_elements(p.content->'events') item
        JOIN affected a ON a.event_id::text=item->>'event_id'
        JOIN LATERAL (SELECT v.* FROM event_versions v WHERE v.event_id=a.event_id AND v.published_at<=p.cutoff
            ORDER BY v.published_at DESC,v.version_no DESC LIMIT 1) v ON true
        WHERE {future_event_parent_sql('v')}""",(lo,hi)).fetchall()]


def refresh_history_conflicts(conn,start,end,guard=None,progress=None):
    """Append corrected source packets when rereads are ready; keep missing proof pending."""
    ids=history_conflict_packets(conn,start,end);report=dict(identified=len(ids),refreshed=0,unchanged=0,pending=[])
    for i,pid in enumerate(ids):
        if guard:guard()
        if progress:progress(i+1,len(ids))
        try:
            result=refresh_packet(conn,pid)
            report['refreshed' if result['status']=='REFRESHED' else 'unchanged']+=1
        except ValueError as exc:
            report['pending'].append(dict(packet_id=str(pid),reason=str(exc)))
    return report


if __name__ == '__main__':
    main()
