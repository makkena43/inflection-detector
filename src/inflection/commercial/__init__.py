"""The commercial discovery route (spec 5.1, 5.2, 18): filings -> passages -> company events -> candidates.

* ``vocabulary``: versioned cue patterns and thresholds (``RULES_VERSION``, ``policy_hash``);
* ``extract``: commercial passages from page text, with page and character span;
* ``resolve``: per-company event identity, dated versions, materiality and priority class;
* ``pipeline``: the database steps (scan, resolve, report, timeline);
* ``python -m inflection.commercial``: the command line.
"""
