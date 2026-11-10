"""ops/bse_daily.py: the daily BSE plan and its runner (no network, no database)."""
import importlib.util
import sys
from datetime import date
from pathlib import Path

spec = importlib.util.spec_from_file_location("bse_daily", Path(__file__).parents[1] / "ops" / "bse_daily.py")
bse_daily = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bse_daily)


def names(steps):
    return [s[0] for s in steps]


def test_plan_runs_every_bse_step_in_order_from_the_day_after_the_last_price():
    steps = bse_daily.plan(date(2026, 11, 10), date(2026, 11, 6), lookback=7, workers=2, python="py")
    assert names(steps) == ["prices", "delivery", "filings", "companies", "fill", "actions", "face values",
                            "filing timing", "downloads 1/2", "downloads 2/2", "results"]
    argv = dict((n, a) for n, a, _ in steps)
    assert argv["prices"] == ["py", "-m", "inflection.prices", "fetch", "2026-11-07", "--to", "2026-11-10", "--exchange", "bse"]
    assert argv["delivery"][3:] == ["fetch-delivery", "2026-11-03", "--to", "2026-11-10"]
    assert argv["fill"][3:6] == ["fill", "2026-11-03", "--to"]
    assert argv["results"][-3:] == ["--bse-only", "--since", "2026-11-03"]
    assert argv["filing timing"][3:] == ["time", "--recent", "7"]
    env = steps[8][2]
    assert (env["FAST"], env["BSE_ONLY"], env["DL_FROM"], env["DL_TO"]) == ("3", "1", "2026-11-03", "2026-11-11")


def test_no_price_step_when_prices_are_current():
    assert "prices" not in names(bse_daily.plan(date(2026, 11, 6), date(2026, 11, 6), python="py"))


def test_dry_run_prints_the_plan_and_runs_nothing(monkeypatch, capsys):
    monkeypatch.setattr(bse_daily, "last_bse_day", lambda dsn: date(2026, 11, 6))
    monkeypatch.setattr(bse_daily.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran")))
    assert bse_daily.main(["--date", "2026-11-10", "--dry-run", "--workers", "9"]) == 0
    out = capsys.readouterr().out
    assert "fetch 2026-11-07 --to 2026-11-10 --exchange bse" in out and "downloads 3/3" in out   # workers capped at 3


def test_runner_reports_failures_and_keeps_going(tmp_path, capsys):
    py = sys.executable
    steps = [("a", [py, "-c", "pass"], {}),
             ("b", [py, "-c", "raise SystemExit(4)"], {}),
             ("downloads 1/2", [py, "-c", "raise SystemExit(3)"], {"_parallel": "downloads"}),   # 3 = nothing left
             ("downloads 2/2", [py, "-c", "pass"], {"_parallel": "downloads", "X": "1"}),
             ("c", [py, "-c", "pass"], {})]
    assert bse_daily.run(steps, tmp_path / "log", {}) == 1
    out = capsys.readouterr().out
    assert "a: ok" in out and "b: FAILED rc=4" in out and "downloads 1/2: ok" in out and "c: ok" in out
