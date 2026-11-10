"""Code triage v1: reviews the engine's core group with fixed rules instead of Haiku (owner decision 2026-11-10).

    code_review.py WEEK [WEEK ...]     review every folder in review_2026/<week>.json that has no review yet

For each folder: code facts (ops/code_facts.py) for the packet's candidate orders, then the fixed decision rules of
ops/order_check.py decide(): stressed -> reject; no real order from an unrelated customer -> reject; not firm or no value
-> watch; firm but below 10% of revenue -> watch; firm, 10%+, not routine -> deep research; routine -> reject unless
thin margin or cheap with growing revenue. The engine's own result is kept once as triage_result.engine.json, and
triage_result.json is rewritten with reviewed_by = "code" so the existing loader and dashboard pick it up.
Same packet in, same decision out: no model and no randomness. Earlier Haiku reviews are left as they are.
"""
import json, os, shutil, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import code_facts as cf  # noqa: E402
oc = cf.oc
import psycopg  # noqa: E402

J = oc.J
VERSION = "code-triage-1"


def reviewed(folder):
    try:
        return json.load(open(f"{J}/triage/{folder}/triage_result.json")).get("reviewed_by") in ("code", "haiku")
    except (OSError, ValueError):
        return False


def review(c, folder, root=None):
    d = f"{root or J + '/triage'}/{folder}"
    r = json.load(open(f"{d}/triage_result.json"))
    if not os.path.exists(f"{d}/triage_result.engine.json"):
        shutil.copyfile(f"{d}/triage_result.json", f"{d}/triage_result.engine.json")
    p = json.load(open(f"{d}/packet.json"))
    facts = cf.answer(p)
    dec = oc.decide(c, p, r["issuer_id"], [facts]) if facts["events"] else dict(action=oc.REJECT, why="no candidate order in the packet", size=None, routine=None)
    stressed = dec.get("why") == "stressed"
    ev = {e["event_id"]: e for e in facts["events"]}.get(dec.get("event")) or {}
    r.update(triage_action=dec["action"], size_pct_of_revenue=dec.get("size"), size_basis="STATED" if dec.get("size") is not None else "UNKNOWN",
             firm=ev.get("firm"), routine=dec.get("routine"), disqualifier="STRESSED" if stressed else None, pass_through=False,
             confidence="RULES", rationale=f"Code triage: {dec.get('why')}" + (f"; order {dec['size']}% of TTM revenue" if dec.get("size") is not None else ""),
             selected_event_id=dec.get("event"), code_facts=facts["events"], reviewed_by="code", triage_rules_version=VERSION)
    tmp = f"{d}/triage_result.json.tmp"
    json.dump(r, open(tmp, "w"), indent=1, default=str)
    os.replace(tmp, f"{d}/triage_result.json")
    return dec["action"]


def main(weeks):
    c = psycopg.connect(oc.DSN, options="-c default_transaction_read_only=on")
    counts = {}
    for w in weeks:
        for f in json.load(open(f"{J}/review_2026/{w}.json")):
            if reviewed(f):
                continue
            a = review(c, f)
            counts[a] = counts.get(a, 0) + 1
    print("code triage:", counts or "nothing new", flush=True)


if __name__ == "__main__":
    if not sys.argv[1:]:
        sys.exit(__doc__)
    main(sys.argv[1:])
