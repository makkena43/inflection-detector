"""Weekly side of the repeatable fact check (ops/order_check.py), run next to the old Haiku review.

    order_check_week.py step WEEK [WEEK ...]   prepares fact checks for filings with no saved facts, saves finished ones,
                                               and exits 3 when Haiku still has work (jobs listed in order_check/live/jobs.json)
    order_check_week.py build                  writes live/order_check.json: old vs new decision and combos for every week since 2025

Haiku reviews each filing twice; a third review is asked only where the two disagree on a fact. Saved facts are never asked
again, so re-running a week always gives the same list. Haiku runs from the project thread (no headless sign-in on this Mac).
"""
import json, os, subprocess, sys
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import order_check as oc  # noqa: E402

J = oc.J
LIVE = f"{J}/order_check/live"
ROOTS = [f"{LIVE}/a", f"{LIVE}/b", f"{LIVE}/c"]
BATCH = 30


def num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def same(a, b):
    """Two reviews of one event agree on every fact the decision uses."""
    if any(a.get(k) != b.get(k) for k in ("real_order", "firm", "related_party", "one_off")):
        return False
    for k in ("amount_cr", "amount_foreign"):
        x, y = num(a.get(k)), num(b.get(k))
        if (x is None) != (y is None) or (x is not None and abs(x - y) > 0.05 * max(abs(x), abs(y), 1e-9)):
            return False
    return True


def answers(root, f, events):
    p = f"{root}/{f}/answer.json"
    if not os.path.exists(p) or set(json.load(open(f"{root}/{f}/candidates.json"))["events"]) != set(events):
        return None
    by = {e.get("event_id"): e for e in json.load(open(p)).get("events") or []}
    return by if set(by) >= set(events) else None


def step(weeks):
    folders = sorted({f for w in weeks for f in json.load(open(f"{J}/review_2026/{w}.json"))})
    need = {r: [] for r in ROOTS}
    ready = []
    for f in folders:
        events = [e["event_id"] for e in oc.candidates(json.load(open(f"{J}/triage/{f}/packet.json")))]
        if not events or oc.from_facts(f) is not None:
            continue
        a, b, c = (answers(r, f, events) for r in ROOTS)
        for r, got in ((ROOTS[0], a), (ROOTS[1], b)):
            if got is None:
                need[r].append(f)
        if a and b:
            if all(same(a[e], b[e]) for e in events) or c:
                ready.append(f)
            else:
                need[ROOTS[2]].append(f)
    if ready:
        oc.save(ROOTS, ready)
    jobs = []
    for r, fs in need.items():
        fresh = [f for f in fs if not os.path.exists(f"{r}/{f}/candidates.json")
                 or set(json.load(open(f"{r}/{f}/candidates.json"))["events"]) != {e["event_id"] for e in oc.candidates(json.load(open(f"{J}/triage/{f}/packet.json")))}]
        if fresh:
            oc.prepare(r, fresh)
        jobs += [dict(run=r, folders=fs[i:i + BATCH]) for i in range(0, len(fs), BATCH)]
    os.makedirs(LIVE, exist_ok=True)
    json.dump(jobs, open(f"{LIVE}/jobs.json", "w"), indent=1)
    waiting = sum(len(j["folders"]) for j in jobs)
    print(f"{len(ready)} saved, {waiting} reviews waiting in {len(jobs)} batches")
    return 3 if jobs else 0


def build():
    """Old vs new decision and combos for every reviewed week since 2025, from saved facts only."""
    sys.path.insert(0, f"{J}/ui")
    import app, combo_flags, psycopg  # noqa: E402
    from order_check import engine
    c = psycopg.connect(app.DSN)
    rows = c.execute("""SELECT DISTINCT ON (week_start, issuer_id) week_start, issuer_id::text, source FROM triage_reviews
                         WHERE is_final AND decided_by LIKE 'claude-haiku%%' AND week_start >= '2025-01-01'
                         ORDER BY week_start, issuer_id, created_at DESC""").fetchall()
    out = []
    for wk, iss, src in rows:
        f = os.path.dirname(src or "").split("triage/")[-1]
        if not f or not os.path.exists(f"{J}/triage/{f}/packet.json"):
            continue
        p = json.load(open(f"{J}/triage/{f}/packet.json"))
        tr = json.load(open(f"{J}/triage/{f}/triage_result.json"))
        label, old = f.split("/")[-1].split("-", 1)[-1], tr.get("triage_action")
        if oc.candidates(p):
            facts = oc.from_facts(f)
            d = oc.decide(c, p, iss, facts) if facts else dict(action=None, why="facts not saved yet", size=None)
        else:
            d = dict(action=oc.REJECT, why="no candidate order", size=None)
        e = wk + timedelta(days=14)
        h = app.holding_changes(iss, e) or {}
        v = p.get("valuation") or {}
        mc = engine.num(v.get("market_cap_cr")) if v.get("market_cap_cr") else None
        rev = engine.revenue(p)
        try:
            opm = app.op_margin(iss, wk)[0]
        except Exception:
            opm = None
        sec, prov = combo_flags.price_source(c, iss, None, e)
        t = combo_flags.price_checks(c, sec, e, prov) if sec else None
        base = dict(issuer_id=iss, opm=opm, mcap_cr=mc, fii_change_pp=h.get("fii_change_pp"),
                    promoter_holding_pct=h.get("promoter_holding_pct"), fii_yoy_pp=h.get("fii_yoy_pp"))

        def flags(size, basis, pick):
            if not t or not pick:
                return []
            o2m = size * rev / 100 / mc if size and rev and mc else None
            return combo_flags.flags(c, dict(base, size_pct_of_revenue=size, size_basis=basis, order_to_mcap=o2m), sec, e, t=t)[0]

        osz = tr.get("size_pct_of_revenue")
        out.append(dict(week=wk.isoformat(), folder=f, label=label, issuer_id=iss, old=old, new=d.get("action"), why=d.get("why"),
                        old_size=osz, new_size=d.get("size"), routine=d.get("routine"),
                        old_combos=flags(osz, tr.get("size_basis"), old == oc.DEEP),
                        new_combos=flags(d.get("size"), "STATED", d.get("action") == oc.DEEP),
                        agree=(old == oc.DEEP) == (d.get("action") == oc.DEEP)))
    res = dict(generated=datetime.now().isoformat(timespec="seconds"), prompt_version=oc.PROMPT_VERSION, rows=out,
               waiting=sum(r["new"] is None for r in out))
    tmp = f"{J}/live/order_check.json.tmp"
    json.dump(res, open(tmp, "w"), default=str)
    os.replace(tmp, f"{J}/live/order_check.json")
    print(f"{len(out)} rows, {res['waiting']} waiting for facts")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    if sys.argv[1] == "step":
        sys.exit(step(sys.argv[2:]))
    if sys.argv[1] == "build":
        build()
