"""Observation-time versions for mutable imports without archived public revision proof.

Historical absence is explicit. A later edit never becomes an earlier fact, even
in public-information reconstruction: these imports do not archive release bytes.
"""
from datetime import datetime, timezone

TABLES={'shareholding_patterns','govt_programmes','programme_mentions','pli_beneficiaries','corporate_actions','financial_scans'}


def snapshot_sql(table):
    if table not in TABLES:raise ValueError('Unsupported supplementary source')
    return f'''(SELECT (jsonb_populate_record(NULL::{table},v.data)).* FROM (
        SELECT DISTINCT ON(source_key) source_key,data,deleted
          FROM supplementary_versions WHERE source_table='{table}' AND observed_at<=%(cutoff)s
          ORDER BY source_key,observed_at DESC,version_id DESC
        ) v WHERE NOT v.deleted)'''


def cutoff_or_now(cutoff):
    cutoff=cutoff or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:raise ValueError('cutoff must be timezone-aware')
    return cutoff


def future_event_parent_sql(alias='v'):
    """Reject inverted ancestry and stale inheritance after a late historical update."""
    if not alias.isascii() or not alias.isidentifier():raise ValueError('Expected internal SQL alias')
    return f"""EXISTS(WITH RECURSIVE ancestry AS (
        SELECT node.event_version_id,node.supersedes_id,node.published_at,node.event_id,node.version_no
          FROM event_versions node WHERE node.event_version_id={alias}.event_version_id
        UNION
        SELECT parent.event_version_id,parent.supersedes_id,parent.published_at,parent.event_id,parent.version_no
          FROM event_versions parent JOIN ancestry child ON parent.event_version_id=child.supersedes_id)
        SELECT 1 FROM ancestry child WHERE
          EXISTS(SELECT 1 FROM event_versions parent WHERE parent.event_version_id=child.supersedes_id
                 AND parent.published_at>child.published_at)
          OR EXISTS(SELECT 1 FROM event_versions late WHERE late.event_id=child.event_id
                 AND late.version_no>child.version_no AND late.published_at<child.published_at))"""
