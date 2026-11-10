"""The "already researched" check, decided by code after the Haiku review (owner decision 2026-11-09).

    already_researched.py [--apply] WEEK [WEEK ...]

A Haiku Deep Research pick is a repeat only when the order it relies on was already a final Deep Research pick for the same
company in an earlier week: that order is the earlier pick's selected event, or an event the earlier pick cited as evidence.
Events are matched by id, or by amount within 3% inside 365 days, because a new filing restating an order gets a new event id.
An earlier Watch or Reject on the order does not block a new pick. Repeats go to WATCH_MILESTONE through
review_2026/repeat_filter.py, which keeps Haiku's verdict and appends a superseding review; nothing is deleted.
Without --apply it only prints what it would do.
"""
import json, os, re, subprocess, sys
from datetime import date

import psycopg

J = os.path.expanduser(os.environ.get("INFLECTION_JOB_ROOT", "~/inflection-jobs"))
DSN = os.environ.get("INFLECTION_DSN", "postgresql:///inflection")


SCALE_CR = {"UNITS": 1e-7, "THOUSAND": 1e-4, "LAKH": 0.01, "MILLION": 0.1, "CRORE": 1, "BILLION": 100}


def amount_cr(event):
    m = re.fullmatch(r"([\d.]+) INR (\w+)", (event or {}).get("amount") or "")
    return float(m[1]) * SCALE_CR[m[2]] if m and m[2] in SCALE_CR else None


def day(event):
    try:
        return date.fromisoformat((event.get("published_at") or "")[:10])
    except ValueError:
        return None


def deciding_event(r, packet):
    """The packet event the decision relies on: the reviewer's selected event, else the event behind its first cited passage."""
    events = {e.get("event_id"): e for e in packet.get("events", [])}
    if r.get("selected_event_id") in events:
        return events[r["selected_event_id"]]
    return next(iter(cited_events(r, packet).values()), None)


def cited_events(r, packet):
    events = {e.get("event_id"): e for e in packet.get("events", [])}
    by_ref = {p.get("evidence_id"): p.get("event_id") for key in ("trigger_passages", "prior_passages", "contradicting_passages") for p in packet.get(key) or []}
    ids = [r.get("selected_event_id"), *(by_ref.get(x, x) for x in r.get("evidence_refs") or [])]
    return {i: events[i] for i in ids if i in events}


def earlier_pick_events(c, issuer, week):
    """[(pick week, event)] for every order cited by this company's earlier Deep Research picks."""
    out = []
    for w, res, source in c.execute("""select r.week_start, t.result, t.source from triage_review_results r join triage_reviews t using (review_id)
                                       where r.is_pick and r.issuer_id = %s and r.week_start < %s order by 1""", (issuer, week)):
        path = f"{J}/{os.path.dirname(source)}/packet.json"
        if os.path.exists(path):
            out += [(str(w), e) for e in cited_events(res, json.load(open(path))).values()]
    return out


def earlier_match(event, earlier):
    amount, published = amount_cr(event), day(event)
    for week, e in earlier:
        if e.get("event_id") == event.get("event_id"):
            return week
        other, seen = amount_cr(e), day(e)
        if amount and other and published and seen and abs(amount - other) <= 0.03 * other and abs((published - seen).days) <= 365:
            return week
    return None


def main(args):
    apply = "--apply" in args
    weeks = [a for a in args if not a.startswith("--")]
    c = psycopg.connect(DSN, options="-c default_transaction_read_only=on")
    repeats = []
    for week in weeks:
        for folder in json.load(open(f"{J}/review_2026/{week}.json")):
            d = f"{J}/triage/{folder}"
            r = json.load(open(f"{d}/triage_result.json"))
            if r.get("triage_action") != "DEEP_RESEARCH" or r.get("repeat_filter") or r.get("reviewed_by") not in ("haiku", "code"):
                continue
            event = deciding_event(r, json.load(open(f"{d}/packet.json")))
            week_found = earlier_match(event, earlier_pick_events(c, r["issuer_id"], week)) if event else None
            if week_found:
                print(f"REPEAT {folder}: {event.get('amount')} was already in the Deep Research pick of {week_found}", flush=True)
                repeats.append(folder)
            elif not event:
                print(f"CHECK {folder}: no deciding order recorded, left as a pick", flush=True)
    print(f"{len(repeats)} repeats", flush=True)
    if apply and repeats:
        sys.exit(subprocess.call([sys.executable, f"{J}/review_2026/repeat_filter.py", *repeats]))


if __name__ == "__main__":
    if not [a for a in sys.argv[1:] if not a.startswith("--")]:
        sys.exit(__doc__)
    main(sys.argv[1:])
