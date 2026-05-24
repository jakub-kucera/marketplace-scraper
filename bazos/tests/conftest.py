import pytest
from django.utils import timezone

from bazos.models import Ad, Category, Query, Section


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
    def _factory(query, bazos_id, topped=False):
        return Ad(
            bazos_id=bazos_id,
            url=f"https://pc.bazos.cz/inzerat/{bazos_id}/test.php",
            name=f"Ad {bazos_id}",
            price_raw="1000 Kč",
            location="Praha",
            view_count=10,
            publish_date=timezone.now(),
            topped=topped,
            short_description="Short desc",
            publisher_name="Seller",
            query=query,
        )
    return _factory
