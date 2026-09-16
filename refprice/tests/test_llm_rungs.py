"""Rungs 3-4 — the only places an LLM is asked anything.

The design point (`PRICE_REFERENCE_SERVICE.md` §5, and the correction to
`HEUREKA_ZBOZI.md` §4d): the model is **never asked to invent an identity**. Rung 4 hands
it a real candidate list that came out of the real catalogue and asks it to pick one or
decline. That is closed-set adjudication — small, auditable, and it degrades to "no
opinion" instead of to a wrong number.

Every test here declines or answers through a stub. Nothing opens a socket, and the
default `LLM_PROVIDER=NULL` means the rungs are inert unless a test says otherwise.
"""
import datetime as dt

import pytest
from django.test import override_settings

from llm.base import LLMResult
from refprice.providers.base import RefProductFacts
from refprice.resolution.llm_rungs import Adjudication, PhraseSuggestion, adjudicate, suggest_phrase

pytestmark = pytest.mark.django_db


def facts(name, pid="1"):
    return RefProductFacts(
        provider="zbozi", product_id=pid, slug=f"s{pid}", name=name, brand="Makita",
        category_id=2543, product_no=None, min_czk=1, median_czk=2, max_czk=3,
        shop_count=5, availability="in_stock", release_date=dt.date(2020, 1, 1),
    )


CANDIDATES = [
    facts("Makita DHP484RFJ", "1"),
    facts("Makita DHP484Z Li-ion 18 V", "2"),
    facts("Makita DHP489Z bez aku", "3"),
]


def answering(value, *, declined_reason=None):
    """A fake `llm.services.complete` that returns one canned result."""
    def _complete(**kwargs):
        _complete.seen = kwargs
        return LLMResult(value=value, raw="{}", provider="FAKE", model="fake-1",
                         tokens_in=300, tokens_out=40, cost_usd=0.0005, latency_ms=10,
                         declined_reason=declined_reason)
    _complete.seen = {}
    return _complete


# ---------------------------------------------------------------------------
# rung 4 — adjudication
# ---------------------------------------------------------------------------

def test_it_returns_the_chosen_candidate(monkeypatch):
    monkeypatch.setattr("refprice.resolution.llm_rungs.complete",
                        answering(Adjudication(index=1, confidence=0.93, reason="exact code")))
    choice = adjudicate("Makita DHP484Z aku vrtacka", CANDIDATES)
    assert choice.facts is CANDIDATES[1]
    assert choice.confidence == 0.93


def test_minus_one_means_none_of_them(monkeypatch):
    """An explicit decline option is what keeps this from inventing a match."""
    monkeypatch.setattr("refprice.resolution.llm_rungs.complete",
                        answering(Adjudication(index=-1, confidence=0.0, reason="no match")))
    assert adjudicate("Something else entirely", CANDIDATES).facts is None


def test_an_out_of_range_index_declines(monkeypatch):
    """A hallucinated index must not become an IndexError three frames up."""
    monkeypatch.setattr("refprice.resolution.llm_rungs.complete",
                        answering(Adjudication(index=99, confidence=0.9, reason="?")))
    assert adjudicate("x", CANDIDATES).facts is None


def test_a_declined_call_declines_the_rung(monkeypatch):
    monkeypatch.setattr("refprice.resolution.llm_rungs.complete",
                        answering(None, declined_reason="budget exhausted"))
    choice = adjudicate("x", CANDIDATES)
    assert choice.facts is None
    assert "budget" in choice.reason


def test_it_reports_what_the_call_cost(monkeypatch):
    monkeypatch.setattr("refprice.resolution.llm_rungs.complete",
                        answering(Adjudication(index=0, confidence=0.8, reason="ok")))
    choice = adjudicate("x", CANDIDATES)
    assert (choice.tokens_in, choice.tokens_out) == (300, 40)
    assert choice.cost_usd == pytest.approx(0.0005)


def test_it_passes_the_candidates_into_the_prompt(monkeypatch):
    fake = answering(Adjudication(index=0, confidence=0.8, reason="ok"))
    monkeypatch.setattr("refprice.resolution.llm_rungs.complete", fake)
    adjudicate("Makita DHP484Z", CANDIDATES)
    prompt = fake.seen["prompt"]
    assert "Makita DHP484Z Li-ion 18 V" in prompt
    assert "Makita DHP484Z" in prompt


def test_it_names_the_prompt_and_version_for_the_audit_log(monkeypatch):
    fake = answering(Adjudication(index=0, confidence=0.8, reason="ok"))
    monkeypatch.setattr("refprice.resolution.llm_rungs.complete", fake)
    adjudicate("x", CANDIDATES)
    assert fake.seen["prompt_name"] == "refprice_adjudicate"
    assert fake.seen["prompt_version"].startswith("v")


def test_an_empty_candidate_list_never_calls_out(monkeypatch):
    called = []
    monkeypatch.setattr("refprice.resolution.llm_rungs.complete",
                        lambda **kw: called.append(kw))
    assert adjudicate("x", []).facts is None
    assert called == []


# ---------------------------------------------------------------------------
# rung 3 — phrase generation
# ---------------------------------------------------------------------------

def test_it_returns_a_phrase(monkeypatch):
    monkeypatch.setattr(
        "refprice.resolution.llm_rungs.complete",
        answering(PhraseSuggestion(phrase="Makita DHP484Z", brand="Makita",
                                   model_code="DHP484Z")),
    )
    assert suggest_phrase("nějaká aku vrtačka Makita", "model DHP484Z").phrase == "Makita DHP484Z"


def test_a_declined_phrase_call_yields_nothing(monkeypatch):
    monkeypatch.setattr("refprice.resolution.llm_rungs.complete",
                        answering(None, declined_reason="no provider"))
    assert suggest_phrase("x", "").phrase == ""


def test_it_names_the_phrase_prompt(monkeypatch):
    fake = answering(PhraseSuggestion(phrase="p", brand="b", model_code="m"))
    monkeypatch.setattr("refprice.resolution.llm_rungs.complete", fake)
    suggest_phrase("x", "")
    assert fake.seen["prompt_name"] == "refprice_query_phrase"


# ---------------------------------------------------------------------------
# inert by default
# ---------------------------------------------------------------------------

@override_settings(LLM_PROVIDER="NULL")
def test_with_the_null_provider_adjudication_simply_declines():
    """No monkeypatching: this is the real path with the shipped default."""
    assert adjudicate("Makita DHP484Z", CANDIDATES).facts is None


@override_settings(LLM_PROVIDER="NULL")
def test_the_null_path_still_leaves_an_audit_row():
    from llm.models import LLMCall
    adjudicate("Makita DHP484Z", CANDIDATES)
    assert LLMCall.objects.filter(prompt_name="refprice_adjudicate").exists()


# ---------------------------------------------------------------------------
# the prompts themselves
# ---------------------------------------------------------------------------

def test_both_prompts_load():
    from llm.prompts import load
    assert load("refprice_adjudicate").template
    assert load("refprice_query_phrase").template


def test_the_adjudication_prompt_offers_an_explicit_decline():
    from llm.prompts import load
    assert "-1" in load("refprice_adjudicate").template
