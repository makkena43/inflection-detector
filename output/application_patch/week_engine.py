"""week_engine.py WEEK : fill every untriaged folder of an exported week with the local engine's decision
(rules 3.3 + local Qwen sizing). Engine DEEP_RESEARCH picks are listed in WEEK/HAIKU_REVIEW.json for a later
Haiku second opinion; nothing here calls a paid model."""
import glob, json, os, sys
import psycopg

sys.path.insert(0, os.path.dirname(__file__))
from engine import triage

B = os.environ.get("TRIAGE_DIR", "/Users/makkenasrinivas/inflection-jobs/triage") + "/"
W = sys.argv[1]
review, n = [], 0
with psycopg.connect("postgresql:///inflection") as c:
    for d in sorted(glob.glob(B + W + "/*/")):
        f = d + "triage_result.json"
        r = json.load(open(f))
        if r.get("triage_action"):
            continue
        p = json.load(open(d + "packet.json"))
        e = triage(p, c, r.get("issuer_id"), use_llm=True)
        r.update(e, engine=f"rules-{os.environ.get('INFLECTION_TRIAGE_RULES', '3.4')}+{e.get('screen_version', 'legacy')}+qwen2.5-3b", confidence="LOW",
                 materiality_status="MATERIAL_POTENTIAL" if (e.get("size_pct_of_revenue") or 0) >= 10 else "MATERIALITY_UNKNOWN")
        json.dump(r, open(f, "w"), indent=2); n += 1
        if e["triage_action"] == "DEEP_RESEARCH":
            review.append(os.path.basename(d.rstrip("/")))
# merge with the list from earlier fills of this week (a re-fill only sees untriaged folders), one entry per folder/issuer
lp = B + W + "/HAIKU_REVIEW.json"
old = json.load(open(lp)) if os.path.exists(lp) else []
iss = lambda f: json.load(open(B + W + "/" + f + "/triage_result.json")).get("issuer_id") if os.path.exists(B + W + "/" + f + "/triage_result.json") else f
merged, seen = [], set()
for f in old + review:
    k = iss(f)
    if f in merged or k in seen: continue
    merged.append(f); seen.add(k)
json.dump(merged, open(lp, "w"))
print(W, "engine filled", n, "deep picks for review", len(review), "on list", len(merged))
