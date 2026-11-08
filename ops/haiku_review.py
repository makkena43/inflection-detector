"""Haiku review of the core group: the local engine's deep-research candidates listed in review_2026/<WEEK>.json.

    haiku_review.py WEEK [WEEK ...]

Uses `claude -p` on Haiku under the Mac's Claude sign-in (never an API key, so it draws on the plan, as earlier reviews did).
Each folder is judged per triage/RUN_REVIEW.txt and overwrites its triage_result.json. Folders that already carry
reviewed_by = haiku are skipped, so a rerun only retries what is missing. Exit codes: 0 all reviewed, 1 some missing, 3 not signed in.
"""
import json, os, shutil, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

J = os.path.expanduser(os.environ.get("INFLECTION_JOB_ROOT", "~/inflection-jobs"))
T, REPO = f"{J}/triage", os.path.expanduser("~/PycharmProjects/inflection-detector")
CLAUDE = shutil.which("claude") or os.path.expanduser("~/.local/bin/claude")
MODEL, CHUNK, WORKERS, TIMEOUT = "claude-haiku-5-5", 8, 2, 1800
ENV = {k: v for k, v in os.environ.items() if k != "ANTHROPIC_API_KEY" and not k.startswith("CLAUDE_CODE") and k != "CLAUDECODE"}


def allowed(scratch):
    return ["Read", "Glob", "Grep", f"Write(/{T}/**)", f"Edit(/{T}/**)", f"Write(/{scratch}/**)",
            "Bash(python3 -I -c:*)",
            f"Bash(cd {REPO} && INFLECTION_DSN=postgresql:///inflection .venv/bin/python -m inflection.packets page:*)"]


def call(prompt, cwd, tools, timeout=TIMEOUT):
    p = subprocess.run([CLAUDE, "-p", "--model", MODEL, "--output-format", "json", "--allowedTools", *tools, "--", prompt],
                       cwd=cwd, env=ENV, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=timeout)
    try:
        return json.loads(p.stdout)
    except ValueError:
        return dict(is_error=True, result=(p.stdout + p.stderr)[:400])


def reviewed(folder):
    try:
        return json.load(open(f"{T}/{folder}/triage_result.json")).get("reviewed_by") == "haiku"
    except (OSError, ValueError):
        return False


def review(args):
    n, week, folders = args
    scratch = f"{J}/live/haiku_scratch/{week}_{n}"
    os.makedirs(scratch, exist_ok=True)
    prompt = (f"Read {T}/RUN_REVIEW.txt and follow it exactly. Do not call any mcp__hearthbot__ tools. Your private scratch directory is {scratch}\n\n"
              f"Your assigned folders are relative to {T}/ (NOT triage_rerun/):\n" + "\n".join(folders) + "\n\nProcess every folder listed, and only those.")
    try:
        out = call(prompt, T, allowed(scratch))
    except subprocess.TimeoutExpired:
        print(week, n, "timed out", flush=True)
        return
    print(week, n, "error:" if out.get("is_error") else "ok", (out.get("result") or "")[:1500], f"cost {out.get('total_cost_usd')}", flush=True)
    shutil.rmtree(scratch, ignore_errors=True)


def main(weeks):
    probe = call("Reply with only: ok", J, [], 120)
    if probe.get("is_error"):
        print("Haiku sign-in check failed:", probe.get("result"), flush=True)
        sys.exit(3)
    todo = [(w, f) for w in weeks for f in json.load(open(f"{J}/review_2026/{w}.json")) if not reviewed(f)]
    print(len(todo), "companies to review", flush=True)
    for attempt in (1, 2):
        chunks = []
        for w in weeks:
            fs = [f for x, f in todo if x == w and not reviewed(f)]
            chunks += [(i, w, fs[i:i + CHUNK]) for i in range(0, len(fs), CHUNK)]
        if not chunks:
            break
        with ThreadPoolExecutor(WORKERS) as ex:
            list(ex.map(review, chunks))
    missing = [f for _, f in todo if not reviewed(f)]
    print("reviewed", len(todo) - len(missing), "missing", missing, flush=True)
    sys.exit(1 if missing else 0)


if __name__ == "__main__":
    if not sys.argv[1:]:
        sys.exit(__doc__)
    main(sys.argv[1:])
