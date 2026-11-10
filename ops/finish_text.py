"""Read every downloaded filing that has no text yet (pipeline_state DOWNLOADED), in batches, so no downloaded document
is left unread. Uses the core pipeline's extract_pending; safe to re-run (only DOWNLOADED rows are touched)."""
import os, sys
from collections import Counter
from pathlib import Path
import psycopg
from inflection.ingest import extract_pending
from inflection.sources.download import Archive

archive = Archive(Path.home() / "inflection-archive")
total = Counter()
with psycopg.connect(os.environ.get("INFLECTION_DSN", "postgresql:///inflection"), autocommit=True) as conn:
    for _ in range(200):
        left = conn.execute("select count(*) from document_publications where pipeline_state = 'DOWNLOADED'").fetchone()[0]
        if not left:
            break
        got = extract_pending(conn, archive, limit=100)
        total.update(got)
        if not sum(got.values()):
            break
    left = conn.execute("select count(*) from document_publications where pipeline_state = 'DOWNLOADED'").fetchone()[0]
print("finished text:", dict(total), "still downloaded-but-unread:", left, flush=True)
sys.exit(0)
