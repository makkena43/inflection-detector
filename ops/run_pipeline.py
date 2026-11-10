"""The one process behind the dashboard's Run tab.

    run_pipeline.py daily     prices and deals, then the strategy lists and the swing scan
    run_pipeline.py weekly    every finished week not yet run: filings, downloads, processing, engine triage, then the Haiku
                              review of that week's core group, then the same strategy lists and swing scan
    run_pipeline.py lists     only the strategy lists and the swing scan

Steps and their state go to live/run_state.json; output goes to logs/run_<mode>_<time>.log. One run at a time.
A failed step is reported and later steps still run where they can; nothing here places an order.
"""
import fcntl, json, os, re, shutil, signal, subprocess, sys
from datetime import date, datetime, timedelta

J = os.path.expanduser(os.environ.get("INFLECTION_JOB_ROOT", "~/inflection-jobs"))
REPO = os.path.expanduser("~/PycharmProjects/inflection-detector")
PY = f"{REPO}/.venv/bin/python"
LIVE, LOGS = f"{J}/live", f"{J}/logs"
STATE = f"{LIVE}/run_state.json"
HISTORY = f"{LIVE}/run_history.json"
V1 = f"{J}/alpha_model/v1_frozen"
MIN_FREE_GB = {"weekly": 10, "daily": 3, "lists": 2}
BUSY = re.compile(r"run_resume\.sh|run_backfill_2026\.sh|dl_worker\.py|run_week_2026\.sh|inflection\.quality_repair")
ENV = {**os.environ, "INFLECTION_DSN": os.environ.get("INFLECTION_DSN", "postgresql:///inflection"), "PYTHONPATH": f"{REPO}/src"}

state = {}
log_path = None
current = None


def now():
    return datetime.now().isoformat(timespec="seconds")


def save():
    tmp = STATE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f)
    os.replace(tmp, STATE)


def log(msg):
    with open(log_path, "a") as f:
        f.write(f"{now()} {msg}\n")


def shell(cmd, cwd=REPO, extra=None):
    """Run a command at low priority with output into the log; returns the exit code."""
    global current
    log("$ " + (cmd if isinstance(cmd, str) else " ".join(cmd)))
    env = {**ENV, **(extra or {})}
    args = ["nice", "-n", "10", "zsh", "-c", cmd] if isinstance(cmd, str) else ["nice", "-n", "10", *cmd]
    with open(log_path, "a") as f:
        current = subprocess.Popen(args, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
        rc = current.wait()
    current = None
    return rc


class Failed(Exception):
    pass


class NeedsYou(Exception):
    pass


def step(name, fn):
    s = dict(name=name, status="running", started=now())
    state["steps"].append(s)
    save()
    log(f"== {name}")
    try:
        s["note"] = fn() or ""
        s["status"] = "done"
    except NeedsYou as e:
        s.update(status="needs_you", note=str(e))
    except Failed as e:
        s.update(status="failed", note=str(e))
    except Exception as e:
        s.update(status="failed", note=f"{type(e).__name__}: {e}")
    s["finished"] = now()
    log(f"== {name}: {s['status']} {s.get('note', '')}")
    save()
    return s["status"] == "done"


def run_or_fail(cmd, what, **kw):
    rc = shell(cmd, **kw)
    if rc:
        raise Failed(f"{what} exited with code {rc}; see the log")


def psql(q):
    return subprocess.check_output(["psql", "-d", "inflection", "-Atc", q], text=True).strip()


def fetch_prices():
    today = date.today()
    start = date.fromisoformat(psql("select max(trade_date) from bhavcopy_rows")) + timedelta(days=1)
    if start > today:
        return "already up to date"
    run_or_fail(f"{PY} -m inflection.prices fetch {start} --to {today}", "price fetch")
    # new listings and post-split ISINs become securities before their rows are copied into prices
    run_or_fail(f"{PY} -m inflection.prices companies", "company build")
    run_or_fail(f"{PY} -m inflection.prices fill {start} --to {today}", "price fill")
    return "prices to " + psql("select max(trade_date) from bhavcopy_rows")


def refresh_deals():
    # BSE-only results and the shareholding walk each take an hour or more, so they stay in the weekly run.
    bad = ["deals"] if shell(f"{PY} -m inflection.deals fetch") else []
    if bad:
        raise Failed("failed: " + ", ".join(bad) + "; see the log")


def asof():
    # The cutoff is exclusive, so tomorrow's date takes in everything published or traded up to now.
    return date.today() + timedelta(days=1)


def build_panel():
    d = asof()
    for folder, script in (("winners_study", "s3_load.py"), ("ranking_model", "r1_prices.py"), ("alpha_model/audit", "b1_ohlc.py")):
        run_or_fail([PY, script], script, cwd=f"{J}/{folder}")
    for script in ("asof_rows.py", "asof_panel.py"):
        run_or_fail([PY, script], script, cwd=V1, extra={"ASOF": d.isoformat()})
    for old in sorted(n for n in os.listdir(V1) if n.startswith("run_2026-11-"))[:-2]:   # only this pipeline's own panels
        shutil.rmtree(f"{V1}/{old}")
    return f"panel as of {d}"


def lists():
    run_or_fail([PY, f"{REPO}/ops/strategy_lists.py", "--asof", asof().isoformat()], "strategy lists")


def swing():
    run_or_fail([PY, f"{REPO}/ops/swing_scan.py"], "swing scan")


def pending_weeks(today=None):
    today = today or date.today()
    this_monday = today - timedelta(days=today.weekday())
    target = this_monday if today.weekday() >= 5 else this_monday - timedelta(days=7)   # a week is ready from its Saturday
    done = re.findall(r"^(\d{4}-\d{2}-\d{2}) done", open(f"{LOGS}/weekly_2026.log").read(), re.M)
    w = date.fromisoformat(max(done)) + timedelta(days=7)
    out = []
    while w <= target:
        out.append(w.isoformat())
        w += timedelta(days=7)
    return out


def run_week(w):
    def go():
        run_or_fail(f"zsh {J}/run_week_2026.sh {w}", f"week {w}")
    return go


def haiku(weeks):
    def go():
        rc = shell([PY, f"{REPO}/ops/haiku_review.py", *weeks])
        if rc == 3:
            raise NeedsYou("Haiku is not signed in on this Mac. Run `claude auth login` in Terminal once, then press Run weekly again.")
        if rc:
            raise Failed("some companies were not reviewed; see the log. Running weekly again retries only those.")
        if shell([PY, f"{J}/load_reviews.py", "2026"]):
            raise Failed("reviews could not be loaded into the database")
        for m in sorted({w[:7] for w in weeks}):
            shell([PY, f"{J}/review_2026/repeat_candidates.py", m])
    return go


def haiku_waiting():
    """Weeks with a Haiku list that still has unreviewed companies, so a week whose Haiku step could not run is retried."""
    out = []
    for f in sorted(os.listdir(f"{J}/review_2026")):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f) and f >= "2026-10-26":
            for folder in json.load(open(f"{J}/review_2026/{f}")):
                try:
                    done = json.load(open(f"{J}/triage/{folder}/triage_result.json")).get("reviewed_by") == "haiku"
                except (OSError, ValueError):
                    done = False
                if not done:
                    out.append(f[:10])
                    break
    return out


def main(mode):
    global log_path, state
    os.makedirs(LIVE, exist_ok=True)
    lock = open(f"{LIVE}/run.lock", "w")
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        sys.exit("A run is already going.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    log_path = f"{LOGS}/run_{mode}_{stamp}.log"
    state = dict(mode=mode, status="running", pid=os.getpid(), started=now(), steps=[], log=log_path)
    save()

    def stop(*_):
        if current:
            current.terminate()
        state.update(status="stopped", finished=now())
        for s in state["steps"]:
            if s["status"] == "running":
                s.update(status="stopped", finished=now())
        save()
        finish()
        os._exit(1)
    signal.signal(signal.SIGTERM, stop)

    busy = [ln for ln in subprocess.check_output(["ps", "-axo", "command"], text=True).splitlines() if BUSY.search(ln)]
    free = shutil.disk_usage("/").free / 1e9

    def guard():
        if busy:
            raise Failed("Another job is running: " + busy[0][:120])
        if free < MIN_FREE_GB[mode]:
            raise Failed(f"Only {free:.1f} GB free; this run needs {MIN_FREE_GB[mode]} GB. Clear disk space, then run again.")
        return f"{free:.1f} GB free"

    if step("Check disk space and other jobs", guard):
        if mode == "daily":
            step("Prices and delivery", fetch_prices)
            step("Deals", refresh_deals)
        elif mode == "weekly":
            weeks = pending_weeks()
            if not weeks:
                step("Filings and triage", lambda: "no finished week is waiting")
            for w in weeks:
                if not step(f"Week {w}: filings, processing, triage", run_week(w)):
                    break
            waiting = haiku_waiting()
            if waiting:
                step("Haiku review of the core group", haiku(waiting))
        if step("Refresh ranking data", build_panel):
            step("Long-term strategy lists", lists)
        step("Short-term swing scan", swing)
    state.update(status="failed" if any(s["status"] == "failed" for s in state["steps"]) else "needs_you" if any(s["status"] == "needs_you" for s in state["steps"]) else "done", finished=now())
    save()
    finish()


def finish():
    hist = json.load(open(HISTORY)) if os.path.exists(HISTORY) else []
    hist = [{k: state.get(k) for k in ("mode", "status", "started", "finished", "log")}] + hist[:19]
    with open(HISTORY, "w") as f:
        json.dump(hist, f)


if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in MIN_FREE_GB:
        sys.exit(__doc__)
    main(sys.argv[1])
