"""`manage.py lookup_reference_price` — the batch and scripting path.

Uses the `NULL`-equivalent of a provider (a stub), so no test here opens a socket.
"""
import datetime as dt
from io import StringIO
from unittest.mock import patch

import pytest
from django.core.management import CommandError, call_command

from bazos.models import Ad, AdDelivery, AdStatus, Marketplace, Query
from refprice.models import RefLookup, RefProduct, RefProductLink
from refprice.providers.base import Candidate, PricePoint, RefProductFacts

pytestmark = pytest.mark.django_db


FACTS = RefProductFacts(
    provider="zbozi", product_id="5325309", slug="makita-dhp484z-li-ion-18-v",
    name="Makita DHP484Z Li-ion 18 V", brand="Makita", category_id=2543,
    product_no=None, min_czk=2870, median_czk=3813, max_czk=5391, shop_count=41,
    availability="in_stock", release_date=dt.date(2017, 6, 14), url="/vyrobek/x/",
)


class StubProvider:
    name = "zbozi"

    def suggest(self, phrase):
        return [Candidate(slug="makita-dhp484z-li-ion-18-v", name=FACTS.name)]

    def fetch(self, slug):
        return FACTS if slug == FACTS.slug else None

    def history(self, product_id, months_back=13):
        return [
            PricePoint(date=dt.date(2025, 9, 1), min_czk=3190, median_czk=4150, max_czk=5000),
            PricePoint(date=dt.date(2026, 9, 1), min_czk=2870, median_czk=3813, max_czk=5391),
        ]

    def search(self, phrase, *, allow_disallowed=False):
        return []


@pytest.fixture(autouse=True)
def _stub_provider():
    with patch("refprice.management.commands.lookup_reference_price.get_provider",
               return_value=StubProvider()):
        yield


@pytest.fixture()
def ad():
    return Ad.objects.create(
        marketplace=Marketplace.BAZOS, external_id=555, name="Makita DHP484Z",
        url="https://pc.bazos.cz/inzerat/555/x.php", price_raw="2 500 Kč", price=2500,
    )


def run(*args, **kwargs) -> str:
    out = StringIO()
    call_command("lookup_reference_price", *args, stdout=out, stderr=out, **kwargs)
    return out.getvalue()


# ---------------------------------------------------------------------------

def test_a_target_is_required():
    with pytest.raises(CommandError):
        run()


def test_an_unknown_ad_is_an_error():
    with pytest.raises(CommandError, match="No Ad"):
        run("--ad", "999999")


def test_it_resolves_one_ad(ad):
    output = run("--ad", str(ad.pk))
    assert "Makita DHP484Z Li-ion 18 V" in output


def test_it_persists_what_it_found(ad):
    run("--ad", str(ad.pk))
    assert RefProduct.objects.count() == 1
    assert RefProductLink.objects.filter(ad=ad).exists()


def test_it_prints_the_median_and_the_shop_count(ad):
    output = run("--ad", str(ad.pk))
    assert "3 813" in output.replace(",", " ")
    assert "41 shops" in output


def test_a_dry_run_writes_nothing(ad):
    run("--ad", str(ad.pk), "--dry-run")
    assert RefProductLink.objects.count() == 0
    assert RefProduct.objects.count() == 0


def test_a_dry_run_says_so(ad):
    assert "Dry run" in run("--ad", str(ad.pk), "--dry-run")


def test_it_still_records_the_attempt(ad):
    """Even a dry run leaves the audit trail — QueryRun's rule applies to the tool too."""
    run("--ad", str(ad.pk))
    assert RefLookup.objects.count() == 1


def test_it_resolves_a_whole_query(ad):
    query = Query.objects.create(text="makita", marketplace=Marketplace.BAZOS)
    AdDelivery.objects.create(ad=ad, query=query, status=AdStatus.PENDING)
    output = run("--query", str(query.pk))
    assert "Makita DHP484Z Li-ion 18 V" in output


def test_a_query_with_no_ads_says_so():
    query = Query.objects.create(text="nothing", marketplace=Marketplace.BAZOS)
    assert "No ads matched" in run("--query", str(query.pk))


def test_refresh_stale_is_quiet_when_nothing_is_stale(ad):
    run("--ad", str(ad.pk))
    assert "Nothing stale" in run("--refresh-stale")


def test_refresh_stale_refetches_an_expired_product(ad):
    run("--ad", str(ad.pk))
    RefProduct.objects.update(fetched_at=dt.datetime(2020, 1, 1, tzinfo=dt.UTC))
    assert "refreshed" in run("--refresh-stale")
