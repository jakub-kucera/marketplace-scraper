"""Rung 5 and the registered-but-unwired filter rule (P29f).

Both are deliberately off by default, for different reasons: rung 5 because the `?q=`
route is robots-disallowed, and the rule because it is inverted (it answers "is there a
reason to *send* this?") so defaulting it on would mute every existing query — exactly
how `price_model` already ships.
"""
import datetime as dt

import pytest

from marketplace.filters import DEFAULT_RULE_NAMES, RULE_REGISTRY, FilterResult, build_rule_engine
from marketplace.models import Ad, AdDelivery, AdStatus, Marketplace, Query
from refprice.models import LookupStatus, RefProduct, RefProductLink
from refprice.providers.base import Candidate, PricePoint, RefProductFacts
from refprice.results import ReferenceRequest
from refprice.rules import ReferencePriceRule
from refprice.services import lookup_reference_price

pytestmark = pytest.mark.django_db


@pytest.fixture()
def ad():
    return Ad.objects.create(
        marketplace=Marketplace.BAZOS, external_id=8080, name="Makita DHP484Z",
        url="https://pc.bazos.cz/inzerat/8080/x.php", price_raw="2 000 Kc", price=2000,
    )


@pytest.fixture()
def delivery(ad):
    query = Query.objects.create(text="makita", marketplace=Marketplace.BAZOS)
    return AdDelivery.objects.create(ad=ad, query=query, status=AdStatus.PENDING)


@pytest.fixture()
def product():
    return RefProduct.objects.create(
        provider="zbozi", product_id="5325309", slug="makita-dhp484z-li-ion-18-v",
        name="Makita DHP484Z Li-ion 18 V", brand="Makita", median_czk=4000,
        min_czk=2870, max_czk=5391, shop_count=41, availability="in_stock",
    )


def link(ad, product, *, confidence=0.9, confirmed=False):
    return RefProductLink.objects.create(
        ad=ad, ad_title=ad.name, provider="zbozi", product=product,
        confidence=confidence, confirmed_by_human=confirmed,
    )


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

def test_the_rule_is_registered():
    assert "reference_price" in RULE_REGISTRY


def test_the_rule_is_not_on_by_default():
    """Inverted rules must never default on — it would mute every existing query."""
    assert "reference_price" not in DEFAULT_RULE_NAMES


def test_a_query_can_name_it_explicitly():
    query = Query.objects.create(text="x", marketplace=Marketplace.BAZOS,
                                 filter_rule_names=["reference_price"])
    engine = build_rule_engine(query)
    assert any(r.name == "reference_price" for r in engine.rules)


def test_marketplace_filters_does_not_import_refprice():
    """Registration happens in refprice's AppConfig.ready, so the dependency points
    inward and deleting this app leaves the pipeline intact."""
    from refprice.tests.import_direction import modules_imported_by

    assert "refprice" not in modules_imported_by("filters.py")


# ---------------------------------------------------------------------------
# the rule's verdicts — every uncertain path is neutral
# ---------------------------------------------------------------------------

def test_it_passes_when_nothing_has_been_looked_up(delivery):
    """A lookup that never ran must not silently drop the ad."""
    assert ReferencePriceRule().apply(delivery)[0] == FilterResult.PASS


def test_it_passes_when_the_ad_has_no_parsed_price(delivery, product):
    delivery.ad.price = None
    delivery.ad.save(update_fields=["price"])
    link(delivery.ad, product)
    assert ReferencePriceRule().apply(delivery)[0] == FilterResult.PASS


def test_it_passes_on_a_thin_market(delivery, product):
    product.shop_count = 1
    product.save(update_fields=["shop_count"])
    link(delivery.ad, product)
    assert ReferencePriceRule().apply(delivery)[0] == FilterResult.PASS


def test_it_passes_on_a_low_confidence_unconfirmed_match(delivery, product):
    link(delivery.ad, product, confidence=0.4)
    assert ReferencePriceRule().apply(delivery)[0] == FilterResult.PASS


def test_a_human_confirmation_overrides_low_confidence(delivery, product):
    link(delivery.ad, product, confidence=0.1, confirmed=True)
    assert ReferencePriceRule().apply(delivery)[0] == FilterResult.APPROVE


def test_it_approves_a_genuine_bargain(delivery, product):
    """2 000 Kc against a 4 000 Kc new median is 50%."""
    link(delivery.ad, product)
    assert ReferencePriceRule().apply(delivery)[0] == FilterResult.APPROVE


def test_it_rejects_an_ad_that_is_not_cheap(delivery, product):
    delivery.ad.price = 3800
    delivery.ad.save(update_fields=["price"])
    link(delivery.ad, product)
    result, reason = ReferencePriceRule().apply(delivery)
    assert result == FilterResult.REJECT
    assert reason is not None and "new price" in reason


def test_the_rejection_reason_names_the_product(delivery, product):
    delivery.ad.price = 3800
    delivery.ad.save(update_fields=["price"])
    link(delivery.ad, product)
    reason = ReferencePriceRule().apply(delivery)[1]
    assert reason is not None and "Makita DHP484Z" in reason


def test_it_never_touches_the_network(delivery, product, monkeypatch):
    """run_filter holds select_for_update locks while rules run. This rule may only read
    links an explicit lookup already persisted."""
    def explode(*args, **kwargs):
        raise AssertionError("the filter rule must not perform network I/O")

    monkeypatch.setattr("refprice.providers.zbozi.ZboziProvider.suggest", explode)
    monkeypatch.setattr("refprice.providers.zbozi.ZboziProvider.fetch", explode)
    link(delivery.ad, product)
    assert ReferencePriceRule().apply(delivery)[0] == FilterResult.APPROVE


# ---------------------------------------------------------------------------
# rung 5
# ---------------------------------------------------------------------------

FOUND = RefProductFacts(
    provider="zbozi", product_id="1", slug="bosch-gsb-18-2-li",
    name="Bosch GSB 18-2-LI", brand="Bosch", category_id=2543, product_no=None,
    min_czk=1500, median_czk=3690, max_czk=5000, shop_count=39,
    availability="in_stock", release_date=dt.date(2015, 1, 1),
)


class SuggestBlindProvider:
    """Suggest finds nothing; the disallowed search does. The measured Bosch case."""

    name = "zbozi"

    def __init__(self):
        self.searched = False

    def suggest(self, phrase):
        return []

    def fetch(self, slug):
        return FOUND if slug == FOUND.slug else None

    def history(self, product_id, months_back=13):
        return [PricePoint(date=dt.date(2026, 9, 1), min_czk=1500, median_czk=3690,
                           max_czk=5000)]

    def search(self, phrase, *, allow_disallowed=False):
        assert allow_disallowed, "escalation must pass the opt-in through"
        self.searched = True
        return [Candidate(slug=FOUND.slug, name=FOUND.name)]


def test_escalation_is_off_by_default(ad):
    provider = SuggestBlindProvider()
    result = lookup_reference_price(ReferenceRequest(title="Bosch GSB 18-2-LI"), ad=ad,
                                    provider=provider)
    assert provider.searched is False
    assert result.status == LookupStatus.NO_MATCH


def test_escalation_finds_what_suggest_cannot(ad):
    provider = SuggestBlindProvider()
    result = lookup_reference_price(
        ReferenceRequest(title="Bosch GSB 18-2-LI", allow_disallowed_search=True),
        ad=ad, provider=provider,
    )
    assert provider.searched is True
    assert result.status == LookupStatus.MATCHED
    assert result.pricing.median_czk == 3690


def test_an_escalated_result_records_that_it_left_the_allowed_path(ad):
    """How a number was obtained travels with the number."""
    result = lookup_reference_price(
        ReferenceRequest(title="Bosch GSB 18-2-LI", allow_disallowed_search=True),
        ad=ad, provider=SuggestBlindProvider(),
    )
    assert result.match.robots_allowed_path is False


def test_an_escalated_result_is_flagged_as_a_caveat_on_the_deal(ad):
    from refprice.services import assess_deal
    result = lookup_reference_price(
        ReferenceRequest(title="Bosch GSB 18-2-LI", allow_disallowed_search=True),
        ad=ad, provider=SuggestBlindProvider(),
    )
    deal = assess_deal(ad_price_czk=1500, reference=result)
    assert any("robots-disallowed" in c for c in deal.caveats)
