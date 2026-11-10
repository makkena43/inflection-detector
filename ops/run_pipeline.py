"""The one process behind the dashboard's Run tab.

    run_pipeline.py daily     all data: prices, deals, filings listed and downloaded, filings processed; packets, engine
                              triage and code triage for any week that has closed; then the strategy lists and the swing scan. Shareholding and BSE-only results run every day, only for companies still missing the latest quarter,
                              capped at 30 minutes each.
    run_pipeline.py weekly    same steps as daily (kept as a button); it reuses today's data pull if there was one
    run_pipeline.py lists     only the strategy lists and the swing scan

Steps and their state go to live/run_state.json; output goes to logs/run_<mode>_<time>.log. One run at a time.
A failed step is reported and later steps still run where they can; nothing here places an order.
"""
import fcntl, json, os, re, shutil, signal, subprocess, sys, time, zlib
from datetime import date, datetime, timedelta

J = os.path.expanduser(os.environ.get("INFLECTION_JOB_ROOT", "~/inflection-jobs"))
REPO = os.path.expanduser("~/PycharmProjects/inflection-detector")
PY = f"{REPO}/.venv/bin/python"
LIVE, LOGS = f"{J}/live", f"{J}/logs"
STATE = f"{LIVE}/run_state.json"
HISTORY = f"{LIVE}/run_history.json"
V1 = f"{J}/alpha_model/v1_frozen"
MIN_FREE_GB = {"weekly": 10, "daily": 5, "lists": 2}
SLOW_STAMP = f"{LIVE}/slow_data_last"
DATA_STAMP = f"{LIVE}/data_last"
SLOW_LIMIT_SECONDS = 1800
RULES = "3.6.2"   # owner 2026-11-04: 3.6 + theme context + order-flow context
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


def shell(cmd, cwd=REPO, extra=None, limit=None):
    """Run a command at low priority with output into the log; returns the exit code, or 124 if it hit the time limit."""
    global current
    log("$ " + (cmd if isinstance(cmd, str) else " ".join(cmd)))
    env = {**ENV, **(extra or {})}
    args = ["nice", "-n", "10", "zsh", "-c", cmd] if isinstance(cmd, str) else ["nice", "-n", "10", *cmd]
    with open(log_path, "a") as f:
        current = subprocess.Popen(args, cwd=cwd, env=env, stdout=f, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            rc = current.wait(timeout=limit)
        except subprocess.TimeoutExpired:
            os.killpg(current.pid, signal.SIGTERM)
            current.wait()
            log(f"stopped at the {limit} s time limit")
            rc = 124
    current = None
    return rc


class Failed(Exception):
    pass


class NeedsYou(Exception):
    pass


RETRY_WAITS = (60, 300)     # a failed step is tried again after 1 minute, then after 5 minutes (owner 2026-11-10)


def step(name, fn):
    s = dict(name=name, status="running", started=now())
    state["steps"].append(s)
    save()
    log(f"== {name}")
    for attempt in range(len(RETRY_WAITS) + 1):
        try:
            s["note"] = fn() or ""
            s["status"] = "done"
        except NeedsYou as e:
            s.update(status="needs_you", note=str(e))
        except Failed as e:
            s.update(status="failed", note=str(e))
        except Exception as e:
            s.update(status="failed", note=f"{type(e).__name__}: {e}")
        if s["status"] != "failed" or attempt == len(RETRY_WAITS):
            break
        log(f"== {name}: failed ({s['note']}); retrying in {RETRY_WAITS[attempt]} s")
        s["note"] = f"retry {attempt + 1} after: {s['note']}"; save()
        time.sleep(RETRY_WAITS[attempt])
    if attempt and s["status"] == "done":
        s["note"] = f"{s['note']} (succeeded on retry {attempt})"
    remember_failure(name, s["status"] == "failed", s.get("note"))
    s["finished"] = now()
    log(f"== {name}: {s['status']} {s.get('note', '')}")
    save()
    return s["status"] == "done"


LAST_OK = f"{LIVE}/daily_last_ok"


def missed_days():
    """Days since the last daily run whose data steps all finished; windowed steps reach back at least this far, so a
    missed day (or week) is processed from where it stopped."""
    try:
        last = date.fromisoformat(open(LAST_OK).read().strip())
    except (OSError, ValueError):
        return 7
    return max(1, (date.today() - last).days)


def remember_failure(name, failed, note):
    """Steps that still failed after their retries, kept across runs so the next run reports what it is catching up."""
    path = f"{LIVE}/failed_steps.json"
    try:
        led = json.load(open(path)) if os.path.exists(path) else {}
    except ValueError:
        led = {}
    if failed:
        led[name] = dict(last_failed=now(), note=note, since=led.get(name, {}).get("since", now()))
    elif name in led:
        led.pop(name)
    with open(path, "w") as f:
        json.dump(led, f, indent=1)


def gap_fill():
    """Weekly sweep (Sundays in the daily run, and the Weekly button): re-check the last 30 days for anything a daily run
    missed. Every command skips work already stored, so this only adds what is missing."""
    today = date.today(); since = today - timedelta(days=30)
    index_closes()
    days = psql(f"""select string_agg(d::text, ' ') from (select distinct trade_date d from index_closes where index_name='Nifty Smallcap 250'
                    and trade_date >= '{since}' except select distinct trade_date from bhavcopy_rows where exchange='NSE') x""")
    missing = [d for d in (days or "").split() if d]
    for d in missing:
        run_or_fail(f"{PY} -m inflection.prices fetch {d} --to {d}", f"price fetch {d}")
    run_or_fail(f"{PY} -m inflection.prices fill {since} --to {today}", "price fill (30 days)")
    run_or_fail(f"{PY} -m inflection.corporate_actions fetch {today - timedelta(days=45)} --to {today + timedelta(days=90)}", "corporate actions (45 days)")
    for ex, segment in (("nse", "equities"), ("nse", "sme"), ("bse", "equity")):
        seg = f"--segment {segment}" if ex == "nse" else ""
        run_or_fail(f"{PY} -m inflection.ingest {ex} {today - timedelta(days=14)} --to {today} {seg} --download 0 --extract 0", f"{ex} {segment} re-listing (14 days)")
    download_filings()
    rc = shell(f"zsh {J}/run_range_2026.sh {today - timedelta(days=14)} {today}")
    rc_bse = shell([PY, f"{REPO}/ops/bse_daily.py", "--workers", "2", "--lookback", "30"], extra={"INFLECTION_DSN": "postgresql:///inflection"})
    notes = [f"{len(missing)} missing price days fetched"] + (["filing re-processing reported gaps; see the log"] if rc else []) + (["BSE 30-day sweep had a failed step"] if rc_bse else [])
    return "; ".join(notes)


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
    run_or_fail(f"{PY} -m inflection.prices fill {start} --to {today}", "price fill")
    return "prices to " + psql("select max(trade_date) from bhavcopy_rows")


def index_closes():
    """NSE index closes (Smallcap 250 and every other NSE index) for each trading day with prices; skips days stored."""
    run_or_fail([PY, f"{J}/index_data/fetch.py"], "index closes", cwd=f"{J}/index_data")
    return "index closes to " + psql("select max(trade_date) from index_closes")


def refresh_deals():
    run_or_fail(f"{PY} -m inflection.deals fetch", "deals")


def refresh_slow():
    """Shareholding and BSE-only results: about 1.5 s per company each, and they only change with quarterly filings."""
    today = date.today()
    last = date.fromisoformat(open(SLOW_STAMP).read().strip()) if os.path.exists(SLOW_STAMP) else None
    full_bse = last is None or (today - last).days >= 7      # the full BSE-only results pull (~1 hour) stays weekly;
                                                           # bse_daily.py takes the last 7 days of BSE results every day
    last_month = (today.month - 1) // 3 * 3                     # the latest finished quarter's final month; 0 means December last year
    quarter = date(today.year, last_month + 1, 1) - timedelta(days=1)
    symbols = psql(f"""select distinct h.value from identifier_history h where h.exchange='NSE' and h.kind='SYMBOL' and h.valid_to is null
                       and not exists (select 1 from shareholding_patterns p where upper(p.symbol)=upper(h.value) and p.period_end >= '{quarter}') order by 1""").split()
    # Each company still missing the quarter is asked once a week (a seventh of them per day), so a daily run makes about
    # 1/7 of the requests instead of ~2,600; a company is checked again within a week of filing.
    symbols = [x for x in symbols if zlib.crc32(x.encode()) % 7 == today.toordinal() % 7]
    path = f"{LIVE}/shareholding_symbols.txt"
    with open(path, "w") as f:
        f.write("\n".join(symbols) + "\n")
    notes, bad = [f"{len(symbols)} companies still missing the {quarter} quarter"], []
    for cmd, what in ((f"{PY} -m inflection.shareholding fetch --symbols {path}", "shareholding"), (f"{PY} -m inflection.bse_results load", "BSE results")):
        if (what == "shareholding" and not symbols) or (what == "BSE results" and not full_bse):
            continue
        rc = shell(cmd, limit=SLOW_LIMIT_SECONDS)
        if rc == 124:
            notes.append(f"{what} stopped at the {SLOW_LIMIT_SECONDS // 60}-minute limit")
        elif rc:
            bad.append(what)
    if bad:
        raise Failed("failed: " + ", ".join(bad) + "; see the log")
    if full_bse:
        with open(SLOW_STAMP, "w") as f:
            f.write(today.isoformat())
    return "; ".join(notes + ([] if full_bse else [f"full BSE results pull next due {last + timedelta(days=7)}"]))


def bse_daily():
    """BSE prices and delivery, BSE filings list, derived splits/bonuses, face values, recent BSE results and BSE-only
    result PDFs (ops/bse_daily.py, 4-8 minutes; every step skips what is stored)."""
    look = max(7, missed_days() + 2)
    rc = shell([PY, f"{REPO}/ops/bse_daily.py", "--workers", "2", "--lookback", str(look)], extra={"INFLECTION_DSN": "postgresql:///inflection"})
    if rc == 2:
        raise Failed("bse_daily stopped: less than 3 GB free")
    if rc:
        raise Failed("a BSE daily step failed; see logs/bse_daily_<date>.log")
    return f"BSE daily steps done (last {look} days)"


def finish_text():
    """Read every downloaded-but-unread filing (any date), so no downloaded document is left without text."""
    run_or_fail([PY, f"{REPO}/ops/finish_text.py"], "finish text", extra={"PYTHONPATH": f"{REPO}/src", "INFLECTION_DSN": "postgresql:///inflection"})
    return psql("select count(*) from document_publications where pipeline_state = 'DOWNLOADED'") + " downloaded files still unread"


PURGE_READ = os.environ.get("INFLECTION_PURGE_READ") == "1"   # off unless the owner asks for files to be removed after reading


def purge_read():
    """Delete downloaded files whose text is fully extracted (the text stays in the database), so documents do not pile up
    on disk; partly read or OCR-pending files are kept for a later pass. A file can always be fetched again."""
    rc = shell([PY, "-m", "inflection.purge", "--archive", os.path.expanduser("~/inflection-archive"), "--max-gb", "0", "--target-gb", "0"])
    if rc:
        raise Failed("purge failed; see the log")
    return "read files purged; archive now " + subprocess.check_output(["du", "-sh", os.path.expanduser("~/inflection-archive")], text=True).split()[0]


def day_triage():
    """Provisional day-by-day triage of the current week (ops/day_triage.py, own run tag; the week's final list is made
    when it closes)."""
    if date.today().weekday() >= 5:
        return "weekend: the closed week is triaged by the weekly path above"
    run_or_fail([PY, f"{REPO}/ops/day_triage.py"], "day triage", extra=TRIAGE_ENV)
    return "today's provisional triage written to live/day_triage.json"


def corporate_actions():
    """Announced dividends and their ex and record dates, from 10 days back to 90 days ahead, for the dividend leg."""
    today = date.today()
    back = max(10, missed_days() + 3)
    run_or_fail(f"{PY} -m inflection.corporate_actions fetch {today - timedelta(days=back)} --to {today + timedelta(days=90)}", "corporate actions")
    return "dividends known through " + psql("select max(ex_date) from corporate_actions where kind='DIVIDEND'")


def list_filings():
    today = date.today()
    for ex, segment in (("nse", "equities"), ("nse", "sme"), ("bse", "equity")):
        # A quiet company stream must advance by verified listing windows, not by its last filing.
        start = psql(f"""select coalesce(((max(r.window_end) at time zone 'Asia/Kolkata')::date - 2), '2026-01-01')
                         from ingestion_runs r join sources s using(source_id)
                         where s.name='{ex}_announcements' and r.segment='{segment}' and r.coverage_status='COMPLETE'""")
        seg = f"--segment {segment}" if ex == "nse" else ""
        run_or_fail(f"{PY} -m inflection.ingest {ex} {start} --to {today} {seg} --download 0 --extract 0", f"{ex} {segment} listing")


def download_filings():
    run_or_fail(f"FAST=3 BSE_ONLY=1 DL_FROM=2026-01-01 EXCHANGES='NSE BSE' WORKERS=3 zsh {J}/run_downloads.sh", "downloads")


def process_filings():
    today = date.today()
    done = re.findall(r"^\S+ \S+ (\d{4}-\d{2}-\d{2}) processed$", open(f"{LOGS}/backfill.log").read(), re.M)
    start = date.fromisoformat(done[-1]) + timedelta(days=1) if done else today.replace(day=1)
    if start > today:
        return "already up to date"
    began = datetime.now().timestamp()
    rc = shell(f"zsh {J}/run_range_2026.sh {start} {today}")
    if rc:
        report = f"{REPO}/output/process_health/report.json"
        if os.path.exists(report) and os.path.getmtime(report) >= began:   # all steps ran; only the completeness gate at the end said no
            checks = json.load(open(report))
            names = [c["key"] for c in checks["checks"] if c.get("blocking")]
            return f"filings processed, with data gaps still open: {', '.join(names)}"
        raise Failed(f"processing exited with code {rc}; see the log")
    return f"processed {start} to {today}"


def data_steps():
    with open(DATA_STAMP, "w") as f:
        f.write(date.today().isoformat())
    step("Prices and delivery", fetch_prices)
    step("BSE daily data", bse_daily)
    step("Index closes", index_closes)
    step("Deals", refresh_deals)
    step("Corporate actions and dividends", corporate_actions)
    step("Shareholding and BSE results", refresh_slow)
    step("List new filings", list_filings)
    step("Download filings", download_filings)
    step("Read any downloaded-but-unread filings", finish_text)
    step("Process filings", process_filings)
    if PURGE_READ:
        step("Remove read documents from disk", purge_read)
    names = ("Prices and delivery", "BSE daily data", "Index closes", "Deals", "Corporate actions and dividends", "Shareholding and BSE results",
             "List new filings", "Download filings", "Process filings")
    if all(x["status"] == "done" for x in state["steps"] if x["name"] in names):
        with open(LAST_OK, "w") as f:
            f.write(date.today().isoformat())


TRIAGE_ENV = {"INFLECTION_TRIAGE_RULES": RULES}


def snapshot_themes():
    today = date.today()
    for args in (f"discover --as-of {today}", "emergent-index", f"emergent --as-of {today}"):
        run_or_fail(f"{PY} -m inflection.themes {args}", f"themes {args.split()[0]}")


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
    run_or_fail([PY, f"{REPO}/ops/short_book.py"], "short-term book")


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


def build_week(w):
    def go():
        done_log = f"{LOGS}/weekly_2026.log"
        if not re.search(rf"^{w} done", open(done_log).read(), re.M):
            if not os.path.isdir(f"{J}/triage/{w}"):
                run_or_fail(f"zsh {J}/triage_week.sh {w}", "packet build", extra=TRIAGE_ENV)
            run_or_fail([PY, f"{J}/engine/week_engine.py", w], "engine triage", extra=TRIAGE_ENV)
            run_or_fail(f"zsh {J}/triage_record_engine.sh {w}", "recording", extra=TRIAGE_ENV)
        run_or_fail([PY, f"{J}/review_2026/build_list.py", w], "review list", extra=TRIAGE_ENV)
        shell([PY, f"{J}/review_2026/coverage_guard.py", w])
        if not re.search(rf"^{w} done", open(done_log).read(), re.M):
            with open(done_log, "a") as f:
                f.write(f"{w} done\n")
        shell([PY, f"{J}/ui/order_terms.py", "--since", "2025-01-01"])
        return f"{len(json.load(open(f'{J}/review_2026/{w}.json')))} companies for code triage"
    return go


def code_triage(weeks):
    """Code triage v1 replaces the Haiku review (owner decision 2026-11-10): fixed rules, no model, nothing to wait for."""
    def go():
        if shell([PY, f"{REPO}/ops/code_review.py", *weeks]):
            raise Failed("code triage failed; see the log")
        if shell([PY, f"{J}/load_reviews.py", "2026"]):
            raise Failed("reviews could not be loaded into the database")
        if shell([PY, f"{REPO}/ops/already_researched.py", "--apply", *weeks]):
            raise Failed("the already-researched check failed; see the log")
        return f"weeks {', '.join(weeks)} reviewed by code"
    return go


def review_waiting():
    """Weeks with a review list that still has unreviewed companies, so a week whose review step could not run is retried."""
    out = []
    for f in sorted(os.listdir(f"{J}/review_2026")):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.json", f) and f >= "2026-10-26":
            for folder in json.load(open(f"{J}/review_2026/{f}")):
                try:
                    done = json.load(open(f"{J}/triage/{folder}/triage_result.json")).get("reviewed_by") in ("haiku", "code")
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
            os.killpg(current.pid, signal.SIGTERM)   # the whole step, including any scripts it started
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
        pulled_today = os.path.exists(DATA_STAMP) and open(DATA_STAMP).read().strip() == date.today().isoformat()
        if mode == "daily" or (mode == "weekly" and not pulled_today):   # weekly reuses today's data pull if there was one
            data_steps()
        if mode == "weekly" or date.today().weekday() == 6:              # weekly gap fill: the Weekly button, and Sundays
            step("Weekly gap fill (last 30 days)", gap_fill)
        # Packets, engine triage and code triage run every day (owner decision 2026-11-10): a week is processed on the
        # first run after it closes, with no Haiku step. Weekly is kept as a button and runs exactly the same steps.
        weeks = pending_weeks()
        if not weeks:
            step("Packets and triage", lambda: "no finished week is waiting")
        else:
            step("Theme snapshot", snapshot_themes)
        for w in weeks:
            if not step(f"Week {w}: packets and engine triage", build_week(w)):
                break
        waiting = review_waiting()
        if waiting:
            step("Code triage of the core group", code_triage(waiting))
        step("This week so far (day-by-day triage)", day_triage)
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
