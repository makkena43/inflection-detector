# Local processing jobs

These are the maintained sources for the existing jobs installed under `~/inflection-jobs`.
They do not start themselves or create new schedules. The weekly job refreshes NSE mainboard,
NSE SME and BSE separately. Results discovery runs year-round over the currently identified NSE
universe. Range jobs write their completion watermark only after processing and the process-health
gate succeed; weekly completion follows successful recording and coverage verification.

`run_range_2026.sh` accepts `INFLECTION_JOB_ROOT`, `INFLECTION_PROJECT_ROOT` and `INFLECTION_PYTHON`
for isolated failure testing. Tests cover a failed results refresh, financial scan and completion gate.
The existing local job directory still supplies download workers and model/recording utilities.

After schema or rule upgrades, run the process-health report to identify the window needing a reread.
Do not mark a window complete manually to conceal missing source coverage. Raw history and existing
review decisions are retained when applying these scripts.
