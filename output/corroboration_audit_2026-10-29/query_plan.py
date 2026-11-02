from pathlib import Path
import psycopg,json
from inflection import queue
from datetime import datetime
class Capture:
 def execute(self,sql,args):self.sql=sql;self.args=args;return self
 def fetchall(self):return []
x=Capture();queue.evaluation_rows(x,datetime.fromisoformat('2026-09-01T00:00:00+05:30'),datetime.fromisoformat('2026-10-01T00:00:00+05:30'))
with psycopg.connect('postgresql:///inflection',autocommit=True) as c:
 c.execute("SET statement_timeout='15s'")
 plan=c.execute('EXPLAIN (FORMAT JSON) '+x.sql,x.args).fetchone()[0]
 Path('output/corroboration_audit_2026-10-29/query_plan.json').write_text(json.dumps(plan,indent=2))
 rows=c.execute(x.sql,x.args).fetchall()
 result=queue.from_rows(rows)
 Path('output/corroboration_audit_2026-10-29/read_smoke.json').write_text(json.dumps(dict(evaluations=len(rows),issuers=len(result))))
 print(dict(evaluations=len(rows),issuers=len(result)))
