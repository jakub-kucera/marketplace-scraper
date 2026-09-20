"""Tests for the admin's Price model page (`bazos/admin_pricing.py`).

What matters is not the layout but that the page cannot quietly mislead: a missing
artifact must be stated rather than looking like an idle model, the coverage denominator
must not flatter itself, and shadow-mode flags must be listed rather than summarised away.
"""
import math

import pytest
from django.contrib.auth import get_user_model
from django.urls import reverse

from bazos.models import Ad, AdPriceScore, Marketplace, PriceType

URL_NAME = "admin:bazos_ad_price_model_page"


@pytest.fixture
def staff_client(client, db):
    user = get_user_model().objects.create_superuser(
        username="pm", email="pm@test.local", password="password"
    )
    client.force_login(user)
    return client


def _ad(n, name="MacBook Pro 14 2023 M3 Max 36GB 1TB", price=45_000, marketplace=Marketplace.BAZOS):
    return Ad.objects.create(
        external_id=n, marketplace=marketplace, url=f"https://x/{n}", name=name,
        price_raw=f"{price} Kc", price=price, price_type=PriceType.EXACT,
        location="Praha", short_description="Stav dobry.", publisher_name="x",
    )


def _score(ad, *, z=None, predicted=None, declined=None):
    return AdPriceScore.objects.create(
        ad=ad, model_name="macbook", model_version="test",
        predicted=predicted,
        residual_log=None if predicted is None else math.log(ad.price / predicted),
        z_score=z, declined_reason=declined,
    )


@pytest.mark.django_db
def test_page_renders_for_staff(staff_client):
    response = staff_client.get(reverse(URL_NAME))

    assert response.status_code == 200
    assert "Coverage" in response.content.decode()


@pytest.mark.django_db
def test_anonymous_visitors_do_not_reach_it(client):
    response = client.get(reverse(URL_NAME))

    assert response.status_code in (302, 403), "the admin_view wrapper must gate this"


@pytest.mark.django_db
def test_funnel_counts_candidates_scored_predicted_and_deals(staff_client):
    for i in range(4):
        _ad(i)                                   # 4 macbook candidates
    _ad(90, name="Dell XPS 15")                  # not a candidate
    _score(Ad.objects.get(external_id=0), predicted=60_000, z=-2.5)
    _score(Ad.objects.get(external_id=1), predicted=46_000, z=-0.2)
    _score(Ad.objects.get(external_id=2), declined="missing year")

    funnel = staff_client.get(reverse(URL_NAME)).context["funnel"]

    assert funnel["candidates"] == 4
    assert funnel["scored"] == 3
    assert funnel["predicted"] == 2
    assert funnel["declined"] == 1
    assert funnel["deals"] == 1


@pytest.mark.django_db
def test_decline_reasons_are_grouped_and_ranked(staff_client):
    for i in range(3):
        _score(_ad(i), declined="missing year")
    _score(_ad(5), declined="damage word: rozbit")

    declines = staff_client.get(reverse(URL_NAME)).context["declines"]

    assert declines[0]["declined_reason"] == "missing year"
    assert declines[0]["n"] == 3
    assert [row["n"] for row in declines] == sorted((row["n"] for row in declines), reverse=True)


@pytest.mark.django_db
def test_would_alert_is_ordered_by_z_not_by_discount(staff_client):
    """A flat percentage is ~1σ for a private seller and ~3σ for a dealer — z is the find."""
    big_discount_weak_z = _score(_ad(1, price=30_000), predicted=50_000, z=-2.1)
    small_discount_strong_z = _score(_ad(2, price=44_000), predicted=50_000, z=-4.8)

    rows = staff_client.get(reverse(URL_NAME)).context["would_alert"]

    assert [r.pk for r in rows] == [small_discount_strong_z.pk, big_discount_weak_z.pk]


@pytest.mark.django_db
def test_a_missing_artifact_is_reported_not_hidden(staff_client, monkeypatch):
    """The failure mode this page exists for: neutral-on-error makes it look idle."""
    from bazos.pricing.estimators.macbook import MacbookPriceModel

    monkeypatch.setattr(type(MacbookPriceModel()), "manifest", property(lambda self: None))

    response = staff_client.get(reverse(URL_NAME))

    assert response.context["artifact"]["loaded"] is False
    assert "No artifact loaded" in response.content.decode()


@pytest.mark.django_db
def test_coverage_denominator_does_not_flatter_itself(staff_client):
    """Unscored candidates must count against coverage, not be excluded from it."""
    for i in range(10):
        _ad(i)
    _score(Ad.objects.get(external_id=0), predicted=50_000)

    funnel = staff_client.get(reverse(URL_NAME)).context["funnel"]

    assert funnel["candidates"] == 10
    assert funnel["scored_pct"] == 10


@pytest.mark.django_db
def test_a_null_discount_does_not_render_a_bare_percent_sign(staff_client):
    """`discount_pct` is nullable; "%" with no number reads as a broken column."""
    ad = _ad(1, price=30_000)
    AdPriceScore.objects.create(
        ad=ad, model_name="macbook", model_version="test",
        predicted=50_000, residual_log=-0.51, z_score=-2.6, discount_pct=None,
    )

    content = staff_client.get(reverse(URL_NAME)).content.decode()

    assert ">%<" not in content and "> %<" not in content
