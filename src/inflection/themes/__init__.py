"""MakroGraph India supply-gap themes inside inflection (no Neo4j, no LLM).

History (2020 to July 2026) is copied once from the makrograph database (`importer`). New filings are tagged and
scored with the same MakroGraph code (`mg_*` modules are vendored verbatim; `discovery` ports the beneficiary query
and conviction formula), so later as_of dates continue the same series. Packets read the latest as_of on or
before their cutoff (`exposure`).
"""
