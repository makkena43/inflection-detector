"""Meaning labels for emergent-theme phrases, from a local model (Ollama), asked once per phrase and cached.

The background contrast in `emergent` removes ordinary filing language, but some words are genuinely specific to
order and capacity sentences without naming a theme: event and status words ("commissioned", "wins", "underway"),
units ("mtpa", "metric tons") and template or marketing words ("documents mentioned", "new range", "skus").  A small
local model answers one yes/no question per candidate phrase.  Answers go to theme_phrase_labels, and snapshots read
only that table: no model call during a weekly run, and a rerun reads the same labels.  Once labels exist, only phrases labelled yes can form themes; a new phrase waits until it is labelled (the weekly
run labels new phrases first when the local model is available).
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from collections import defaultdict
from typing import Callable, Optional

from . import emergent

PROMPT_VERSION = "theme-phrase-v4"
LABEL_SPEC_FACTOR = 0.25   # label phrases down to a quarter of the snapshot threshold: a phrase can be far more
                           # concentrated in one 2-year window than over the whole index
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:3b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")

PROMPT = """You label short phrases taken from Indian listed companies' announcements of orders received, \
capacity added and products launched.
Question: could this phrase name a specific kind of thing a company makes, sells, supplies or builds? That \
includes any product, material, chemical, drug, component, equipment, technology, industry or sector, type of \
plant or power plant, infrastructure asset, or type of construction or service work.
Examples of yes: power transformers, bess, battery energy storage, civil works, green hydrogen, mumbai metro, \
sulphuric acid, substation, solar modules, solar power plant, nuclear power, waste water treatment, artillery \
shells, light metal casting, access control, toothpaste, deodorants, rolling stock, injection moulding, \
large-scale renewable energy, power plants.
Answer "no" only when the phrase clearly names no specific kind of thing: an event or status word, a unit or \
quantity, a place or country on its own, a company or person's name, a date, or a generic business, marketing \
or letter word. Examples of no: commissioned, wins, underway, terminated, ramp-up, mtpa, metric tons, new range, \
variants, skus, tailored, documents mentioned, enclosed press release, investor correspondence, pipeline, \
capex, saudi arabia, strategic, platform, new product, product launch, product range, power order, greenfield, \
brownfield, capacity addition, factory shed, plant assets, epc project.
A plant, facility, project or product phrase must say WHAT it makes or builds: "water treatment plant", \
"solar power plant", "seamless pipe" are yes; "new facility", "new manufacturing", "manufacturing lines", \
"new plants", "plant assets", "new models", "four new products", "speciality products", "brownfield facility", \
"module capacity" are no.
If unsure, answer yes.
Phrase: "{phrase}"
Answer with one word: yes or no."""


def ask_ollama(phrase: str, model: str = DEFAULT_MODEL, url: str = OLLAMA_URL, timeout: int = 60) -> str:
    body = json.dumps({"model": model, "prompt": PROMPT.format(phrase=phrase), "stream": False,
                       "options": {"temperature": 0, "num_predict": 3}}).encode()
    req = urllib.request.Request(url.rstrip("/") + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())["response"].strip()


def parse(answer: str) -> Optional[bool]:
    a = answer.strip().strip('."\'').lower()
    if a.startswith("yes"):
        return True
    if a.startswith("no"):
        return False
    return None


def candidates(conn, spec_min: float = emergent.SPEC_MIN * LABEL_SPEC_FACTOR) -> list[str]:
    """Phrases that could become themes in some week: used by MIN_COMPANIES+ companies over the whole index, at least
    LABEL_SPEC_FACTOR of the snapshot specificity threshold, and not yet labelled under this prompt version. Most
    used first."""
    bg = emergent.load_background(conn)
    if bg is None:
        raise RuntimeError("no background counts; run emergent-background first")
    bgc, n_bg = bg
    cos: dict[str, set] = defaultdict(set)
    pas: dict[str, int] = defaultdict(int)
    n = 0
    for iss, phs in conn.execute("SELECT issuer_id, phrases FROM theme_phrase_mentions WHERE version = %s",
                                 (emergent.VERSION,)):
        n += 1
        for p in phs or ():
            cos[p].add(iss)
            pas[p] += 1
    done = {r[0] for r in conn.execute("SELECT phrase FROM theme_phrase_labels WHERE prompt_version = %s",
                                       (PROMPT_VERSION,)).fetchall()}
    out = [p for p, c in cos.items() if len(c) >= emergent.MIN_COMPANIES and p not in done
           and (pas[p] / n) / ((bgc.get(p, 0) + 1) / (n_bg + 1)) >= spec_min]
    out.sort(key=lambda p: (-len(cos[p]), p))
    return out


def label(conn, limit: Optional[int] = None, model: str = DEFAULT_MODEL,
          spec_min: float = emergent.SPEC_MIN * LABEL_SPEC_FACTOR,
          ask: Callable[[str], str] = None, stop_file: Optional[str] = None) -> dict:
    """Ask the model about each unlabelled candidate phrase and store the answer (one row per phrase). Unclear answers
    are not stored, so they are asked again next time. Stops early when `stop_file` exists."""
    ask = ask or (lambda p: ask_ollama(p, model))
    todo = candidates(conn, spec_min)
    if limit:
        todo = todo[:limit]
    out = {"candidates": len(todo), "yes": 0, "no": 0, "unclear": 0, "seconds": 0.0}
    t0 = time.time()
    for p in todo:
        if stop_file and os.path.exists(stop_file):
            out["stopped"] = True
            break
        ans = ask(p)
        v = parse(ans)
        if v is None:
            out["unclear"] += 1
            continue
        conn.execute("""INSERT INTO theme_phrase_labels (prompt_version, phrase, is_theme, answer, model)
                        VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""", (PROMPT_VERSION, p, v, ans[:40], model))
        out["yes" if v else "no"] += 1
    out["seconds"] = round(time.time() - t0, 1)
    emergent._LABEL_CACHE.clear()
    return out
