"""Completion and source-generation rules shared by decision readers."""
from collections import defaultdict


def ready_sql(alias='cs',observed_cutoff=None):
    """A scan is not a replacement until every extracted mention is resolved.

    Zero-match and skipped-category readings can withdraw a previous interpretation.
    Missing identity/time and unfinished interpretations cannot withdraw it.
    """
    if not alias.isascii() or not alias.isidentifier():raise ValueError('Internal alias required')
    clock=f' AND {alias}.scanned_at<={observed_cutoff}' if observed_cutoff else ''
    late=f' OR r.resolved_at>{observed_cutoff}' if observed_cutoff else ''
    return f"""({alias}.status IN ('SCANNED','SKIPPED_CATEGORY')
        AND {alias}.issuer_id IS NOT NULL AND {alias}.published_at IS NOT NULL {clock}
        AND NOT EXISTS(SELECT 1 FROM commercial_mentions m LEFT JOIN commercial_resolutions r USING(mention_id)
          WHERE m.text_artifact_id={alias}.text_artifact_id AND m.rules_version={alias}.rules_version
            AND (r.mention_id IS NULL {late})))"""


class ReadingHistory:
    """Indexed observed source readings for actual-system replay cutoffs."""
    def __init__(self,rows):
        self.docs={};self.by_doc=defaultdict(list);self.cache={};self.cache_cutoff=None
        for issuer,doc,artifact,policy,text_status,text_created,known_at,published,events in rows:
            self.docs[artifact]=doc
            self.by_doc[(issuer,doc)].append((artifact,policy,text_status,text_created,known_at,published,events or []))

    def retain(self,rows,cutoff):
        if self.cache_cutoff!=cutoff:self.cache.clear();self.cache_cutoff=cutoff
        out=[]
        for row in rows:
            if row[3]!='COMMERCIAL':out.append(row);continue
            filing=(row[8] or {}).get('filing') or {};artifact=filing.get('text_artifact_id')
            doc=self.docs.get(artifact)
            if not doc:out.append(row);continue
            key=(str(row[0]),doc,artifact,cutoff)
            if key not in self.cache:
                eligible=[r for r in self.by_doc[(str(row[0]),doc)]
                    if r[4]<=cutoff and r[3]<=cutoff and r[5]<cutoff
                    and (r[2]=='COMPLETE' or r[0]==artifact)]
                self.cache[key]=max(eligible,key=lambda r:(r[3],r[4],r[0],r[1])) if eligible else None
            latest=self.cache[key]
            policy=(row[8] or {}).get('_policy_version') or filing.get('rules_version')
            identities={e.get('event_id') for e in (row[8] or {}).get('events',[])}
            if (policy is None or latest is None or (latest[0]==artifact and latest[1]==policy)
                    or identities.intersection(latest[6])):
                if latest and policy is not None and (latest[0]!=artifact or latest[1]!=policy):
                    copy=list(row);events=[]
                    for event in (row[8] or {}).get('events',[]):
                        event=dict(event)
                        if event.get('event_id') not in latest[6]:
                            event['details']=dict(event.get('details') or {},source_recheck_conflict=True,
                                                  source_reading_withdrawn=True)
                        events.append(event)
                    copy[8]=dict(row[8],events=events);row=tuple(copy)
                out.append(row)
        return out


def superseded_sql(artifact,policy,issuer,event,current,cutoff,observed=None):
    """Internal SQL expressions only: a completed reread no longer supports an event."""
    clock=f' AND reading.created_at<={observed}' if observed else ''
    return f"""EXISTS(SELECT 1 FROM text_artifacts original JOIN text_artifacts reading USING(document_version_id)
        JOIN commercial_scans replacement ON replacement.text_artifact_id=reading.text_artifact_id
        WHERE original.text_artifact_id={artifact} AND replacement.issuer_id={issuer}
          AND {ready_sql('replacement',observed)} AND replacement.published_at<={cutoff} {clock}
          AND (reading.text_artifact_id=original.text_artifact_id OR reading.status='COMPLETE')
          AND (reading.created_at,reading.text_artifact_id)>=(original.created_at,original.text_artifact_id)
          AND ((replacement.rules_version={current} AND {policy}<>{current}) OR
              substring(replacement.rules_version from '^commercial-([0-9]+)$')::integer>
                substring({policy} from '^commercial-([0-9]+)$')::integer OR
              (replacement.rules_version={policy} AND
               (reading.created_at,reading.text_artifact_id)>(original.created_at,original.text_artifact_id)))
          AND NOT EXISTS(SELECT 1 FROM commercial_mentions m JOIN commercial_resolutions r USING(mention_id)
             WHERE m.text_artifact_id=replacement.text_artifact_id AND m.rules_version=replacement.rules_version
               AND r.event_id={event}))"""
