"""Load every triage decision on disk for the given years into triage_reviews, then compute outcomes.

python load_reviews.py 2021 2022
Final decisions come from triage/<week>/<folder>/triage_result.json; earlier rule versions kept in
snapshot folders (triage_v1, _v2, _v3, _v31, _v32, triage_feb_v32) are loaded with is_final = false.
"""
import glob, json, os, statistics, sys
from datetime import date, timedelta

import psycopg
from psycopg.types.json import Jsonb
from inflection.packets.review_binding import review_packet

J = "/Users/makkenasrinivas/inflection-jobs/"
YEARS = sys.argv[1:] or ["2021", "2022"]
SNAPSHOTS = {"triage_v1": "triage-rules-1", "triage_v2": "triage-rules-2", "triage_v3": "triage-rules-3",
             "triage_v31": "triage-rules-3.1", "triage_v32": "triage-rules-3.2", "triage_feb_v32": "triage-rules-3.2"}
ACTIONS = {"DEEP_RESEARCH", "WATCH_MILESTONE", "REJECT_WITH_REASON", "DATA_REPAIR", "DEFER_BUDGET"}


def who(week, r):
    if r.get("reviewed_by") == "code":
        return "code triage v1 (fixed rules, no model)"
    if r.get("reviewed_by"):
        return "claude-haiku-5-5 (second opinion on local engine)"
    if r.get("prefilter"):
        return "prefilter rules-3.3"
    if r.get("engine"):
        return "local engine " + str(r["engine"])
    if r.get("carried_from"):
        return "carried forward from " + r["carried_from"]
    return "claude-sonnet-5-5" if week < "2021-02-01" else "claude-haiku-5-5"


def boolish(v):
    return v if isinstance(v, bool) else None


def num(v):
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def load(c, root, final, default_rules):
    n = 0
    for y in YEARS:
        for f in sorted(glob.glob(f"{root}/{y}-*/*/triage_result.json")):
            week = f.split("/")[-3]
            if "." in week:
                continue
            try:
                r = json.load(open(f))
            except ValueError:
                continue
            if r.get("triage_action") not in ACTIONS or not r.get("issuer_id"):
                continue
            pj = os.path.join(os.path.dirname(f), "packet.json")
            pid = json.load(open(pj)).get("packet_id") if os.path.exists(pj) else None
            try:
                pid=review_packet(c,r,pid,week)
                if final and pid is None and r['triage_action'] in ('DEEP_RESEARCH','REJECT_WITH_REASON'):
                    raise ValueError('Unbound decision requires its original packet basis')
            except (ValueError,TypeError) as exc:
                report=os.path.join(J,'pending_review_imports.jsonl')
                with open(report,'a') as pending:
                    pending.write(json.dumps(dict(source=f,issuer_id=r.get('issuer_id'),week=week,reason=str(exc)))+'\n')
                print('Review pending:',f,str(exc))
                continue
            cur = c.execute(
                """INSERT INTO triage_reviews (week_start, issuer_id, label, packet_id, packet_hash, decided_by, rules_version,
                       triage_action, size_pct_of_revenue, size_basis, firm, routine, disqualifier, pass_through, confidence,
                       rationale, result, is_final, source)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (week, r["issuer_id"], os.path.basename(os.path.dirname(f)).split("-", 1)[-1], pid, r.get("packet_hash"),
                 who(week, r), r.get("triage_rules_version") or default_rules, r["triage_action"],
                 num(r.get("size_pct_of_revenue")), r.get("size_basis"), boolish(r.get("firm")), boolish(r.get("routine")),
                 r.get("disqualifier"), boolish(r.get("pass_through")), r.get("confidence"), r.get("rationale"), Jsonb(r),
                 final, f.replace(J, "")))
            n += cur.rowcount
    return n


def outcomes(c):
    px = lambda s, d: c.execute("""SELECT close FROM prices_split_bonus_adjusted WHERE security_id=%s AND provider='nse_bhavcopy'
                                    AND trade_date BETWEEN %s AND %s AND close > 0 ORDER BY trade_date LIMIT 1""",
                                (s, d, d + timedelta(days=10))).fetchone()
    med = {}

    def market(e, days):
        if (e, days) not in med:
            r = c.execute("""with a as (select distinct on (security_id) security_id, close from prices_split_bonus_adjusted where provider='nse_bhavcopy' and trade_date between %s and %s and close>0 order by security_id, trade_date),
              b as (select distinct on (security_id) security_id, close from prices_split_bonus_adjusted where provider='nse_bhavcopy' and trade_date between %s and %s and close>0 order by security_id, trade_date)
              select b.close/a.close-1 from a join b using(security_id)""", (e, e + timedelta(days=10), e + timedelta(days=days), e + timedelta(days=days + 10))).fetchall()
            med[(e, days)] = statistics.median(float(x[0]) for x in r) if r else None
        return med[(e, days)]

    rows = c.execute("""SELECT r.review_id, r.week_start, r.issuer_id FROM triage_reviews r
                         WHERE r.is_final AND NOT EXISTS (SELECT 1 FROM triage_review_outcomes o WHERE o.review_id = r.review_id)""").fetchall()
    n = 0
    for rid, week, iss in rows:
        sec = c.execute("""SELECT h.security_id FROM securities s JOIN identifier_history h USING (security_id) WHERE s.issuer_id=%s
                           AND h.exchange='NSE' AND h.kind='SYMBOL' ORDER BY h.valid_to NULLS FIRST LIMIT 1""", (iss,)).fetchone()
        e = week + timedelta(days=14)
        p0 = px(sec[0], e) if sec else None
        for days in (182, 365, 730):
            p1 = px(sec[0], e + timedelta(days=days)) if p0 else None
            m = market(e, days)
            sr = float(p1[0]) / float(p0[0]) - 1 if p0 and p1 else None
            c.execute("""INSERT INTO triage_review_outcomes (review_id, horizon_days, entry_date, stock_return, market_median, excess_return)
                         VALUES (%s,%s,%s,%s,%s,%s)""", (rid, days, e, sr, m, sr - m if sr is not None and m is not None else None))
        n += 1
    return n


def main():
    with psycopg.connect("postgresql:///inflection", autocommit=True) as c:
        print("final", load(c, J + "triage", True, "triage-rules-3.3"))
        for snap, rv in SNAPSHOTS.items():
            if os.path.isdir(J + snap):
                print(snap, load(c, J + snap, False, rv))
        print("outcomes for", outcomes(c), "decisions")

if __name__=='__main__':main()
