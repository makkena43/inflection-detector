# Local dashboard

Maintained source for the dashboard installed at `~/inflection-jobs/ui/`; copy `app.py`, `index.html` and `combo_flags.py` there and
restart it. It binds only to `127.0.0.1:8765`.

Tabs: Run (daily or weekly process, `ops/run_pipeline.py`), Haiku outputs (C7 by default), Long-term momentum
(`ops/strategy_lists.py`, Stack A by default), Short-term momentum (`ops/swing_scan.py`).

Run outputs live in `~/inflection-jobs/live/`: `run_state.json`, `strategies.json`, `swing.json`, and `books/` (one file per strategy
holding its month-by-month decisions). The Haiku step needs `claude auth login` done once on the Mac; it draws on the plan, not an API key.
