"""Day-by-day triage of the current week (owner decision 2026-11-10: "make everything day by day").

    day_triage.py [YYYY-MM-DD]     build today's provisional shortlist, packets, engine triage and code triage

Each day gets its own run tag (INFLECTION_RUN_TAG=day-<date>), so the week's real shortlist (run tag 'base', frozen at
the week's end by the weekly path) is never touched. Packets go to ~/inflection-jobs/triage_day/<date>/<week>/.
Engine deep-research picks get the code triage (ops/code_review.py), then combo checks; the result is written to
live/day_triage.json for the dashboard. Nothing is recorded in triage_reviews: the final record for the week is still
made once the week closes. No model is called.
"""
import json, os, subprocess, sys
from datetime import date, timedelta

HERE = os.path.dirname(os.path.abspath(__file__)); REPO = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import code_review as cr  # noqa: E402
oc = cr.oc
J = oc.J
PY = f"{REPO}/.venv/bin/python"
MIN_FREE_GB = 6


def run(cmd, env):
    print("$", " ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=REPO, env=env, check=True, stdout=subprocess.DEVNULL if "assemble" in cmd or "export" in cmd else None)


def combos(c, p, folder_root, f, dec):
    sys.path.insert(0, f"{J}/ui")
    import app, combo_flags
    from order_check import engine
    tr = json.load(open(f"{folder_root}/{f}/triage_result.json")); iss = tr["issuer_id"]
    e = date.today()
    h = app.holding_changes(iss, e) or {}
    v = p.get("valuation") or {}
    mc = engine.num(v.get("market_cap_cr")) if v.get("market_cap_cr") else None; rev = engine.revenue(p)
    try:
        opm = app.op_margin(iss, e)[0]
    except Exception:
        opm = None
    sec, prov = combo_flags.price_source(c, iss, None, e)
    t = combo_flags.price_checks(c, sec, e, prov) if sec else None
    if not t or dec != oc.DEEP:
        return [], t
    size = tr.get("size_pct_of_revenue")
    r = dict(issuer_id=iss, opm=opm, mcap_cr=mc, fii_change_pp=h.get("fii_change_pp"), promoter_holding_pct=h.get("promoter_holding_pct"),
             fii_yoy_pp=h.get("fii_yoy_pp"), size_pct_of_revenue=size, size_basis="STATED", order_to_mcap=size * rev / 100 / mc if size and rev and mc else None)
    return combo_flags.flags(c, r, sec, e, t=t)[0], t


def main(day):
    week = day - timedelta(days=day.weekday())
    root = f"{J}/triage_day/{day}"
    env = dict(os.environ, INFLECTION_DSN=oc.DSN, INFLECTION_RUN_TAG=f"day-{day}", INFLECTION_VERIFY_MODEL="local-clf-1",
               INFLECTION_PACKET_THEMES="1", TRIAGE_DIR=root, PYTHONPATH=f"{REPO}/src")
    import shutil, psycopg
    if shutil.disk_usage("/").free < MIN_FREE_GB * 1e9:
        print(f"skipped: less than {MIN_FREE_GB} GB free"); return
    os.makedirs(root, exist_ok=True)
    if not os.path.isdir(f"{root}/{week}"):
        run([PY, "-m", "inflection.triage", "build", "--week", str(week), "--mode", "PUBLIC_INFORMATION_RECONSTRUCTION"], env)
        # Only companies with a commercial event recorded since yesterday get a packet today; the full week is built
        # once it closes. This keeps a day's build to minutes instead of the whole shortlist (about 2,600 companies).
        with psycopg.connect(oc.DSN, options="-c default_transaction_read_only=on") as c0:
            syms = [r[0] for r in c0.execute("""
                SELECT DISTINCT h.value FROM triage_shortlist_items i JOIN triage_shortlists s USING (shortlist_id)
                  JOIN event_versions v ON v.event_version_id = ANY(i.trigger_event_version_ids)
                  JOIN securities sec ON sec.issuer_id = i.issuer_id
                  JOIN identifier_history h ON h.security_id = sec.security_id AND h.kind = 'SYMBOL' AND h.exchange = 'NSE' AND h.valid_to IS NULL
                 WHERE s.run_tag = %s AND s.week_start = %s AND i.slot IN ('RANKED', 'UPDATE', 'EXPLORATION')
                   AND v.recorded_at >= %s::date - 1""", (f"day-{day}", week, day))]
        print(len(syms), "companies with a new event since yesterday", flush=True)
        for sym in syms:
            try:
                run([PY, "-m", "inflection.packets", "assemble", "--week", str(week), "--symbol", sym], env)
                run([PY, "-m", "inflection.packets", "export", "--week", str(week), "--symbol", sym, "--out", root], env)
            except subprocess.CalledProcessError as e:
                print("packet failed:", sym, e, flush=True)
        os.makedirs(f"{root}/{week}", exist_ok=True)
    run([PY, f"{J}/engine/week_engine.py", str(week)], env)
    import psycopg
    c = psycopg.connect(oc.DSN)
    picks = json.load(open(f"{root}/{week}/HAIKU_REVIEW.json")) if os.path.exists(f"{root}/{week}/HAIKU_REVIEW.json") else []
    rows = []
    for name in picks:
        f = f"{week}/{name}"
        if json.load(open(f"{root}/{f}/triage_result.json")).get("reviewed_by") != "code":
            cr.review(c, f, root=root)
        tr = json.load(open(f"{root}/{f}/triage_result.json"))
        p = json.load(open(f"{root}/{f}/packet.json"))
        cmb, t = combos(c, p, root, f, tr["triage_action"])
        rows.append(dict(day=str(day), week=str(week), folder=f, label=name.split("-", 1)[-1], issuer_id=tr["issuer_id"], action=tr["triage_action"],
                         why=tr.get("rationale"), size=tr.get("size_pct_of_revenue"), combos=cmb, last_close=None if not t else None))
    out = dict(day=str(day), week=str(week), generated=date.today().isoformat(), engine_picks=len(picks), rows=rows)
    tmp = f"{J}/live/day_triage.json.tmp"; json.dump(out, open(tmp, "w"), default=str); os.replace(tmp, f"{J}/live/day_triage.json")
    hist = f"{J}/live/day_triage_history.json"
    h = json.load(open(hist)) if os.path.exists(hist) else []
    h = [x for x in h if x["day"] != str(day)] + [out]
    json.dump(h, open(hist, "w"), default=str)
    print(f"{day}: engine picks {len(picks)}, code picks {sum(r['action'] == oc.DEEP for r in rows)}, with a combo {sum(bool(r['combos']) for r in rows)}")


if __name__ == "__main__":
    main(date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today())
