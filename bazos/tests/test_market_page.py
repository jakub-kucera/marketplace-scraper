"""Tests for the admin's Market page (`bazos/admin_market.py`).

Three panels, three ways they could quietly mislead: latency counting blocked attempts or
downtime as cycles, price drops including Vinted's manufactured ones, and archive gaps
either invented before a marketplace existed or missed once it did.
"""
from datetime import timedelta

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone

from bazos.models import Ad, Marketplace, PriceChange, PriceType, QueryRun

URL_NAME = "admin:bazos_ad_market_page"


@pytest.fixture
def staff_client(client, db):
    user = get_user_model().objects.create_superuser(
        username="mk", email="mk@test.local", password="password"
    )
    client.force_login(user)
    return client


def _run(query, minutes_ago, success=True):
    start = timezone.now() - timedelta(minutes=minutes_ago)
    return QueryRun.objects.create(query=query, run_start=start, run_end=start, success=success)


def _ad(n, marketplace=Marketplace.BAZOS, price=10_000, days_ago=0):
    ad = Ad.objects.create(
        external_id=n, marketplace=marketplace, url=f"https://x/{n}", name=f"Ad {n}",
        price_raw=f"{price} Kc", price=price, price_type=PriceType.EXACT,
        location="Praha", short_description="x", publisher_name="x",
    )
    if days_ago:
        Ad.objects.filter(pk=ad.pk).update(created=timezone.now() - timedelta(days=days_ago))
    return ad


@pytest.mark.django_db
def test_page_renders(staff_client):
    response = staff_client.get(reverse(URL_NAME))

    assert response.status_code == 200
    assert "Archive" in response.content.decode()


@pytest.mark.django_db
def test_anonymous_visitors_do_not_reach_it(client):
    assert client.get(reverse(URL_NAME)).status_code in (302, 403)


@pytest.mark.django_db
def test_cycle_time_measures_successful_runs_only(staff_client, query):
    """A blocked attempt is not a cycle — the retry loop absorbs it within the same pass.

    Counting failures would report the ~50% block rate as latency.
    """
    _run(query, 90)
    for offset in (75, 60, 45):          # three blocked attempts in between
        _run(query, offset, success=False)
    _run(query, 30)                      # next success, 60 minutes after the first

    card = staff_client.get(reverse(URL_NAME)).context["latency"][0]

    assert card["cycles"] == 1
    assert card["median"] == pytest.approx(60, abs=0.5)


@pytest.mark.django_db
def test_downtime_is_not_counted_as_a_cycle(staff_client, query):
    """A two-day gap is the scraper having been down; one outage must not own the median."""
    _run(query, 60 * 24 * 3)
    _run(query, 90)
    _run(query, 60)

    card = staff_client.get(reverse(URL_NAME)).context["latency"][0]

    assert card["cycles"] == 1, "the multi-day gap should be discarded"
    assert card["median"] == pytest.approx(30, abs=0.5)


@pytest.mark.django_db
def test_price_drops_exclude_vinted(staff_client):
    """Vinted's PLN conversion manufactures changes for listings nobody edited (§5.4)."""
    bazos_ad = _ad(1)
    vinted_ad = _ad(2, marketplace=Marketplace.VINTED)
    for ad in (bazos_ad, vinted_ad):
        PriceChange.objects.create(ad=ad, old_price="20000", new_price="15000",
                                   old_price_amount=20_000, new_price_amount=15_000)

    drops = staff_client.get(reverse(URL_NAME)).context["biggest_drops"]

    assert [row["ad"].pk for row in drops] == [bazos_ad.pk]


@pytest.mark.django_db
def test_biggest_drops_are_ranked_by_percentage_not_absolute(staff_client):
    cheap = _ad(1, price=1_000)
    pricey = _ad(2, price=90_000)
    PriceChange.objects.create(ad=cheap, old_price="2000", new_price="1000",
                               old_price_amount=2_000, new_price_amount=1_000)     # −50%
    PriceChange.objects.create(ad=pricey, old_price="100000", new_price="90000",
                               old_price_amount=100_000, new_price_amount=90_000)  # −10%

    drops = staff_client.get(reverse(URL_NAME)).context["biggest_drops"]

    assert [row["ad"].pk for row in drops] == [cheap.pk, pricey.pk]


@pytest.mark.django_db
def test_a_missing_day_is_reported_as_a_gap(staff_client):
    """The panel's whole value is the absence: a lost day can never be backfilled."""
    for days_ago in (0, 1, 2, 4, 5):     # day 3 missing
        for n in range(5):
            _ad(days_ago * 10 + n, days_ago=days_ago)

    row = staff_client.get(reverse(URL_NAME)).context["archive"][0]

    assert row["gap_count"] >= 1
    assert (timezone.localdate() - timedelta(days=3)) in row["gaps"]


@pytest.mark.django_db
def test_days_before_a_marketplace_existed_are_not_gaps(staff_client):
    """Vinted started 2026-08-23; the months before are not data loss."""
    for days_ago in (0, 1):
        _ad(100 + days_ago, marketplace=Marketplace.VINTED, days_ago=days_ago)

    rows = {row["label"]: row for row in staff_client.get(reverse(URL_NAME)).context["archive"]}

    assert rows["Vinted"]["days_watched"] <= 2
    assert rows["Vinted"]["gap_count"] == 0
