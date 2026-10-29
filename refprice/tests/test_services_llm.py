"""Rungs 3-4 inside `lookup_reference_price` — off unless the caller opts in.

Kept separate from `test_services.py` so the rule-only path stays readable there: rungs
0-2 are the whole feature, and these two are an escalation for the cases the rules
measurably cannot see.
"""
import datetime as dt

import pytest

from marketplace.models import Ad, Marketplace
from refprice.models import LookupStatus
from refprice.providers.base import Candidate, PricePoint, RefProductFacts
from refprice.resolution.llm_rungs import Choice, PhraseSuggestion
from refprice.results import ReferenceRequest
from refprice.services import assess_deal, lookup_reference_price

pytestmark = pytest.mark.django_db


def product(name="Makita DHP484Z Li-ion 18 V", *, shops=41):
    return RefProductFacts(
        provider="zbozi", product_id="5325309", slug="makita-dhp484z-li-ion-18-v",
        name=name, brand="Makita", category_id=2543, product_no=None, min_czk=2870,
        median_czk=3813, max_czk=5391, shop_count=shops, availability="in_stock",
        release_date=dt.date(2017, 6, 14), url="/vyrobek/x/",
    )


class StubProvider:
    name = "zbozi"

    def __init__(self, facts=None):
        self._facts = facts or {"makita-dhp484z-li-ion-18-v": product()}

    def suggest(self, phrase):
        return [Candidate(slug="makita-dhp484z-li-ion-18-v", name="?")]

    def fetch(self, slug):
        return self._facts.get(slug)

    def history(self, product_id, months_back=13):
        return [
            PricePoint(date=dt.date(2025, 9, 1), min_czk=3190, median_czk=4150, max_czk=5000),
            PricePoint(date=dt.date(2026, 9, 1), min_czk=2870, median_czk=3813, max_czk=5391),
        ]

    def search(self, phrase, *, allow_disallowed=False):
        return []


@pytest.fixture()
def ad():
    return Ad.objects.create(
        marketplace=Marketplace.BAZOS, external_id=4242, name="Makita DHP484Z",
        url="https://pc.bazos.cz/inzerat/4242/x.php", price_raw="2 500 Kc", price=2500,
    )


def unmatched_by_rules():
    """A candidate whose catalogue name carries no model code, so the rules must reject
    it and rung 4 is the only way through."""
    return StubProvider({"makita-dhp484z-li-ion-18-v": product(name="Makita Bez Kodu")})


def with_llm(title="Makita DHP484Z"):
    return ReferenceRequest(title=title, use_llm=True)


def chose_first(**over):
    defaults = dict(confidence=0.88, reason="same tool", called=True,
                    tokens_in=300, tokens_out=40, cost_usd=0.0005)
    defaults.update(over)
    return lambda title, considered: Choice(considered[0], **defaults)


# ---------------------------------------------------------------------------

def test_the_llm_is_not_consulted_by_default(ad, monkeypatch):
    """`use_llm` defaults False, so a rule-only deployment never spends anything."""
    called = []
    monkeypatch.setattr("refprice.services.adjudicate", lambda *a, **k: called.append(a))
    lookup_reference_price(ReferenceRequest(title="Makita DHP484Z"), ad=ad,
                           provider=unmatched_by_rules())
    assert called == []


def test_adjudication_rescues_a_match_the_rules_rejected(ad, monkeypatch):
    """The measured shape: the right answer is in the list, the rules cannot see it."""
    monkeypatch.setattr("refprice.services.adjudicate", chose_first())
    result = lookup_reference_price(with_llm(), ad=ad, provider=unmatched_by_rules())
    assert result.status == LookupStatus.MATCHED
    assert result.match.method == "LLM"


def test_an_llm_match_reports_what_it_cost(ad, monkeypatch):
    monkeypatch.setattr("refprice.services.adjudicate", chose_first())
    result = lookup_reference_price(with_llm(), ad=ad, provider=unmatched_by_rules())
    assert result.cost.llm_calls == 1
    assert result.cost.usd == pytest.approx(0.0005)
    assert result.cost.llm_tokens_in == 300


def test_an_llm_decline_leaves_the_result_as_no_match(ad, monkeypatch):
    monkeypatch.setattr(
        "refprice.services.adjudicate",
        lambda title, considered: Choice(None, reason="none of them", called=True),
    )
    result = lookup_reference_price(with_llm(), ad=ad, provider=unmatched_by_rules())
    assert result.status == LookupStatus.NO_MATCH


def test_an_llm_match_is_flagged_as_a_caveat_on_the_deal(ad, monkeypatch):
    """An unconfirmed machine match is exactly the thing a human should be told about."""
    monkeypatch.setattr("refprice.services.adjudicate", chose_first())
    result = lookup_reference_price(with_llm(), ad=ad, provider=unmatched_by_rules())
    deal = assess_deal(ad_price_czk=1500, reference=result)
    assert any("LLM" in caveat for caveat in deal.caveats)


def test_a_thin_llm_match_is_still_reported_as_no_market(ad, monkeypatch):
    monkeypatch.setattr("refprice.services.adjudicate", chose_first())
    provider = StubProvider({"makita-dhp484z-li-ion-18-v":
                             product(name="Makita Bez Kodu", shops=1)})
    result = lookup_reference_price(with_llm(), ad=ad, provider=provider)
    assert result.status == LookupStatus.NO_MARKET


def test_an_unsearchable_title_asks_the_llm_for_a_phrase(ad, monkeypatch):
    monkeypatch.setattr(
        "refprice.services.suggest_phrase",
        lambda title, description: PhraseSuggestion("Makita DHP484Z", "Makita", "DHP484Z"),
    )
    result = lookup_reference_price(with_llm(title="nove, se zarukou, 128GB"), ad=ad,
                                    provider=StubProvider())
    assert result.status == LookupStatus.MATCHED
    assert result.match.phrase_used == "Makita DHP484Z"


def test_an_unsearchable_title_without_llm_still_declines(ad):
    result = lookup_reference_price(ReferenceRequest(title="nove, se zarukou, 128GB"),
                                    ad=ad, provider=StubProvider())
    assert result.status == LookupStatus.DECLINED
