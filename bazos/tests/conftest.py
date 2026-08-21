import pytest
from django.utils import timezone

from bazos.models import Ad, AdDelivery, AdStatus, Category, Query, Section


@pytest.fixture
def section(db):
    return Section.objects.create(name="PC", bazos_id="PC", url="pc")


@pytest.fixture
def category(section):
    return Category.objects.create(name="Notebooky", url="notebook", bazos_id=10, section=section)


@pytest.fixture
def query(category):
    return Query.objects.create(
        text="macbook",
        category=category,
        location_center="12345",
        location_radius=25,
        price_lower=0,
        price_upper=0,
        new_query=False,
        ignore_first_run=True,
        load_full_description=False,
    )


@pytest.fixture
def make_ad():
    """`query` is not stored on `Ad` (it moved to `AdDelivery` in the Ad/AdDelivery
    split — see docs/refactor/AD_DELIVERY_SPLIT_SPEC.md) but stays a required parameter
    here: call sites pass it through to `make_delivery(ad, query)` right after, and
    keeping the same signature avoids a mechanical rename across ~120 call sites.
    """
    def _factory(query, bazos_id, topped=False):
        return Ad(
            external_id=bazos_id,
            marketplace="bazos",
            url=f"https://pc.bazos.cz/inzerat/{bazos_id}/test.php",
            name=f"Ad {bazos_id}",
            price_raw="1000 Kč",
            location="Praha",
            view_count=10,
            publish_date=timezone.now(),
            topped=topped,
            short_description="Short desc",
            publisher_name="Seller",
        )
    return _factory


@pytest.fixture
def make_delivery():
    """Create (and by default save) the AdDelivery for an already-saved `ad`."""
    def _factory(ad, query, status=AdStatus.PENDING, save=True):
        delivery = AdDelivery(ad=ad, query=query, status=status)
        if save:
            delivery.save()
        return delivery
    return _factory
