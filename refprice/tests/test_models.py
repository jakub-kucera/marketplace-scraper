"""The four tables, and the constraints that make a second lookup cheap.

Grain is the whole design (PRICE_REFERENCE_SERVICE.md §6): `RefProduct` is keyed on the
*product*, not the ad, because many ads map to one catalogue entry — that is what makes
the feature cheap to run. `RefProductLink` is the per-ad join, and its `confirmed_by_human`
column is the labelled corpus that explicit invocation exists to produce.
"""
import datetime as dt

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from bazos.models import Ad, Marketplace
from refprice.models import (
    LookupStatus,
    MatchMethod,
    RefLookup,
    RefPricePoint,
    RefProduct,
    RefProductLink,
)

pytestmark = pytest.mark.django_db


@pytest.fixture()
def product():
    return RefProduct.objects.create(
        provider="zbozi", product_id="5325309", slug="makita-dhp484z-li-ion-18-v",
        name="Makita DHP484Z Li-ion 18 V", brand="Makita", category_id=2543,
        median_czk=3813, min_czk=2870, max_czk=5391, shop_count=41,
        availability="in_stock",
    )


@pytest.fixture()
def ad():
    return Ad.objects.create(
        marketplace=Marketplace.BAZOS, external_id=12345,
        name="Makita DHP484Z aku vrtacka", url="https://pc.bazos.cz/inzerat/12345/x.php",
        price_raw="2 500 Kc", price=2500,
    )


# ---------------------------------------------------------------------------
# RefProduct
# ---------------------------------------------------------------------------

def test_a_product_is_unique_per_provider_and_id(product):
    with pytest.raises(IntegrityError), transaction.atomic():
        RefProduct.objects.create(
            provider="zbozi", product_id="5325309", slug="other", name="Other",
            shop_count=1,
        )


def test_the_same_id_on_another_provider_is_a_different_row(product):
    RefProduct.objects.create(
        provider="heureka", product_id="5325309", slug="x", name="X", shop_count=1
    )
    assert RefProduct.objects.count() == 2


def test_has_market_is_true_with_two_or_more_shops(product):
    assert product.has_market is True


def test_has_market_is_false_with_one_shop():
    """A discontinued entry keeps one stale offer. That is not a market price."""
    thin = RefProduct.objects.create(
        provider="zbozi", product_id="1", slug="s", name="N", shop_count=1,
        median_czk=549000,
    )
    assert thin.has_market is False


def test_a_freshly_saved_product_is_fresh(product):
    assert product.is_fresh(dt.timedelta(days=1)) is True


def test_a_product_goes_stale(product):
    RefProduct.objects.filter(pk=product.pk).update(
        fetched_at=timezone.now() - dt.timedelta(days=9)
    )
    product.refresh_from_db()
    assert product.is_fresh(dt.timedelta(days=7)) is False


def test_it_keeps_the_manufacturer_part_number():
    """Stored so a churned product id can be re-resolved — ZBOZI_API.md §9.2 flags id
    stability as unmeasured, and productNo is the only other key either site exposes."""
    row = RefProduct.objects.create(
        provider="zbozi", product_id="2", slug="s", name="N", shop_count=3,
        product_no="SM-G973FZWDXEZ",
    )
    assert RefProduct.objects.get(pk=row.pk).product_no == "SM-G973FZWDXEZ"


# ---------------------------------------------------------------------------
# RefPricePoint
# ---------------------------------------------------------------------------

def test_a_price_point_is_unique_per_product_and_date(product):
    RefPricePoint.objects.create(product=product, date=dt.date(2026, 9, 1), median_czk=3800)
    with pytest.raises(IntegrityError), transaction.atomic():
        RefPricePoint.objects.create(product=product, date=dt.date(2026, 9, 1), median_czk=3900)


def test_price_points_come_back_oldest_first(product):
    for day in (3, 1, 2):
        RefPricePoint.objects.create(product=product, date=dt.date(2026, 9, day), median_czk=100 * day)
    dates = [p.date for p in product.price_points.all()]
    assert dates == sorted(dates)


def test_re_fetching_updates_a_point_rather_than_duplicating_it(product):
    """The series is append-only in intent, merged in practice: the newest point is
    today's and its value moves during the day."""
    RefPricePoint.objects.update_or_create(
        product=product, date=dt.date(2026, 9, 16), defaults={"median_czk": 3800}
    )
    RefPricePoint.objects.update_or_create(
        product=product, date=dt.date(2026, 9, 16), defaults={"median_czk": 3813}
    )
    assert product.price_points.count() == 1
    assert product.price_points.get().median_czk == 3813


def test_points_die_with_their_product(product):
    RefPricePoint.objects.create(product=product, date=dt.date(2026, 9, 1), median_czk=1)
    product.delete()
    assert RefPricePoint.objects.count() == 0


# ---------------------------------------------------------------------------
# RefProductLink
# ---------------------------------------------------------------------------

def test_a_link_joins_an_ad_to_a_product(ad, product):
    link = RefProductLink.objects.create(
        ad=ad, ad_title=ad.name, provider="zbozi", product=product,
        confidence=0.9, method=MatchMethod.RULE, phrase_used="Makita DHP484",
    )
    assert link.product == product


def test_one_link_per_ad_and_provider(ad, product):
    RefProductLink.objects.create(ad=ad, ad_title=ad.name, provider="zbozi", product=product)
    with pytest.raises(IntegrityError), transaction.atomic():
        RefProductLink.objects.create(ad=ad, ad_title=ad.name, provider="zbozi", product=product)


def test_deleting_the_ad_keeps_the_link_and_its_title(ad, product):
    """`QueryChange.query_label`'s trick: "what was this matched to" still answers after
    the ad is gone, and the confirmations stay usable as training data."""
    RefProductLink.objects.create(
        ad=ad, ad_title="Makita DHP484Z aku vrtacka", provider="zbozi", product=product
    )
    ad.delete()
    link = RefProductLink.objects.get()
    assert link.ad is None
    assert link.ad_title == "Makita DHP484Z aku vrtacka"


def test_a_link_is_unconfirmed_by_default(ad, product):
    link = RefProductLink.objects.create(ad=ad, ad_title=ad.name, provider="zbozi", product=product)
    assert link.confirmed_by_human is False


def test_a_link_can_record_a_human_rejection_without_a_product(ad):
    """"A person looked and said none of these match" is worth storing — it is a negative
    label, and the next run should not re-offer the same wrong candidate."""
    link = RefProductLink.objects.create(
        ad=ad, ad_title=ad.name, provider="zbozi", product=None,
        confirmed_by_human=True, method=MatchMethod.MANUAL,
    )
    assert link.product is None and link.confirmed_by_human is True


def test_the_evidence_is_stored_as_json(ad, product):
    link = RefProductLink.objects.create(
        ad=ad, ad_title=ad.name, provider="zbozi", product=product,
        evidence={"rejected": [{"slug": "dewalt-kit", "why": "bundle"}]},
    )
    link.refresh_from_db()
    assert link.evidence["rejected"][0]["why"] == "bundle"


# ---------------------------------------------------------------------------
# RefLookup — one row per attempt, failures included
# ---------------------------------------------------------------------------

def test_a_lookup_records_a_successful_attempt(ad, product):
    RefLookup.objects.create(
        ad=ad, phrase_used="Makita DHP484", provider="zbozi",
        status=LookupStatus.MATCHED, http_requests=4, llm_calls=0,
    )
    assert RefLookup.objects.get().status == LookupStatus.MATCHED


def test_a_lookup_records_a_failure_too(ad):
    """QueryRun's rule: "tried and found nothing" is a different fact from "never tried"."""
    RefLookup.objects.create(
        ad=ad, phrase_used="x", provider="zbozi", status=LookupStatus.NO_MATCH,
        http_requests=1,
    )
    assert RefLookup.objects.get().status == LookupStatus.NO_MATCH


def test_every_result_status_is_storable(ad):
    for status in LookupStatus.values:
        RefLookup.objects.create(ad=ad, phrase_used="x", provider="zbozi", status=status)
    assert RefLookup.objects.count() == len(LookupStatus.values)


def test_lookups_survive_the_ad(ad):
    RefLookup.objects.create(ad=ad, phrase_used="x", provider="zbozi",
                             status=LookupStatus.NO_MATCH)
    ad.delete()
    assert RefLookup.objects.count() == 1
