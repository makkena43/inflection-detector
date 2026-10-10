"""The financial discovery route (spec 18.1): year-on-year checks on results XBRL figures, fed into
the same priority classes and candidate evaluations as the commercial route.

``rules`` holds the checks and the priority decision as pure functions; ``pipeline`` runs them
against the database.  Figures come from ``inflection.financials`` (the XBRL fetch and load)."""
