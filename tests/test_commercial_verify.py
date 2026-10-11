"""Model check of commercial passages, with a fake client (no network)."""

import json
from datetime import datetime
from types import SimpleNamespace

from inflection.asof import IST
from inflection.commercial import pipeline, verify
from inflection.commercial.verify import Passage, ask, context_window

from test_commercial import SEBI_ANNEX, _filing, _seed


class FakeClient:
    """Answers every request with ``answer`` (a dict, a raw string, or "refusal"); records requests."""

    def __init__(self, answer):
        self.answer, self.requests = answer, []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.requests.append(kw)
        if self.answer == "refusal":
            return SimpleNamespace(stop_reason="refusal", content=[], usage=None)
        text = self.answer if isinstance(self.answer, str) else json.dumps(self.answer)
        return SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=text)],
                               usage=SimpleNamespace(input_tokens=900, output_tokens=40))


P = Passage("m1", "ABC Limited", None, "Outcome of Board Meeting", "ORDER",
            "The Company has received an order worth Rs. 120 crore.", "…context…")


def test_context_window_finds_the_quote_in_whitespace_normalised_text():
    page = "Header line\n\nThe Company   has received\nan order worth Rs. 120 crore.\nFooter"
    out = context_window(page, "The Company has received an order worth Rs. 120 crore.", chars=7)
    assert out == "…r line The Company has received an order worth Rs. 120 crore. Footer"
    assert context_window("nothing here", "missing quote") == "missing quote"


def test_ask_reads_the_structured_answer_and_sends_the_schema():
    c = FakeClient({"verdict": "REJECTED", "family": "NONE", "reason": "A court order."})
    v = ask(c, P)
    assert (v.verdict, v.family, v.reason, v.input_tokens) == ("REJECTED", None, "A court order.", 900)
    req = c.requests[0]
    assert req["model"] == verify.MODEL and req["output_config"]["format"]["schema"] == verify.SCHEMA
    assert "ABC Limited" in req["messages"][0]["content"] and "120 crore" in req["messages"][0]["content"]


def test_refusals_and_unreadable_answers_are_uncertain_not_rejected():
    assert ask(FakeClient("refusal"), P).verdict == "UNCERTAIN"
    assert ask(FakeClient("not json"), P).verdict == "UNCERTAIN"
    assert ask(FakeClient({"verdict": "MAYBE", "family": "ORDER", "reason": "x"}), P).verdict == "UNCERTAIN"


def test_rejected_passages_are_left_off_the_companys_events(db):
    iss, src = _seed(db)
    _filing(db, iss, src, 1, datetime(2026, 1, 20, 18, 5, tzinfo=IST), ["Cover letter", SEBI_ANNEX])
    pipeline.scan(db)
    out = verify.verify_pending(db, FakeClient({"verdict": "REJECTED", "family": "NONE", "reason": "boilerplate"}))
    assert out["REJECTED"] >= 1 and out["input_tokens"] == 900 * out["REJECTED"]
    assert verify.verify_pending(db, FakeClient({})) == {}                    # nothing is verified twice
    res = pipeline.resolve(db)
    assert res["REJECTED_BY_CHECK"] == out["REJECTED"] and not res["NEW"] and not res["evaluations"]


def test_confirmed_passages_resolve_as_before(db):
    iss, src = _seed(db)
    _filing(db, iss, src, 1, datetime(2026, 1, 20, 18, 5, tzinfo=IST), ["Cover letter", SEBI_ANNEX])
    pipeline.scan(db)
    verify.verify_pending(db, FakeClient({"verdict": "CONFIRMED", "family": "ORDER", "reason": "an order"}))
    res = pipeline.resolve(db)
    assert res["NEW"] >= 1 and not res["REJECTED_BY_CHECK"]


def test_api_errors_are_not_stored_so_they_are_retried(db):
    iss, src = _seed(db)
    _filing(db, iss, src, 1, datetime(2026, 1, 20, 18, 5, tzinfo=IST), ["Cover letter", SEBI_ANNEX])
    pipeline.scan(db)

    class Broken(FakeClient):
        def _create(self, **kw):
            raise ConnectionError("down")
    assert verify.verify_pending(db, Broken({}))["ERROR"] >= 1
    assert db.execute("SELECT count(*) FROM commercial_verifications").fetchone()[0] == 0


def test_verdicts_are_kept_per_model_and_resolve_reads_the_configured_one(db):
    iss, src = _seed(db)
    _filing(db, iss, src, 1, datetime(2026, 1, 20, 18, 5, tzinfo=IST), ["Cover letter", SEBI_ANNEX])
    pipeline.scan(db)
    other = "claude-haiku-5-5" if verify.MODEL != "claude-haiku-5-5" else "claude-opus-5-5"
    verify.verify_pending(db, FakeClient({"verdict": "REJECTED", "family": "NONE", "reason": "x"}), model=other)
    assert verify.pending(db, model=other) == [] and verify.pending(db)          # the configured model still to do
    res = pipeline.resolve(db)
    assert res["NEW"] >= 1 and not res["REJECTED_BY_CHECK"]                     # other model's verdicts ignored
