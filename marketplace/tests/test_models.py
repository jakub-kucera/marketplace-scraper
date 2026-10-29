import pytest
from django.core.exceptions import ValidationError

from marketplace.const import BAZOS_BASE_URL
from marketplace.models import AdStatus, Query


@pytest.mark.django_db
def test_section_full_url_uses_subdomain(section):
    assert section.full_url == "https://pc.bazos.cz"


@pytest.mark.django_db
def test_section_full_url_scheme_is_preserved(section):
    assert section.full_url.startswith("https://")


@pytest.mark.django_db
def test_category_full_url_joins_section_url(category):
    assert category.full_url == "https://pc.bazos.cz/notebook"


@pytest.mark.django_db
def test_query_url_with_section_returns_section_full_url(query, section):
    query.category = None
    query.section = section
    assert query.url == section.full_url


@pytest.mark.django_db
def test_query_url_with_category_returns_category_full_url(query, category):
    assert query.url == category.full_url


@pytest.mark.django_db
def test_query_url_without_section_or_category_returns_base_url(query):
    query.section = None
    query.category = None
    assert query.url == BAZOS_BASE_URL


@pytest.mark.django_db
def test_query_url_section_takes_precedence_over_category(section, category):
    query = Query(
        text="test",
        section=section,
        category=None,
        location_radius=25,
        price_lower=0,
        price_upper=0,
    )
    assert query.url == section.full_url


@pytest.mark.django_db
def test_price_constraint_rejects_lower_greater_than_upper(db):
    query = Query(price_lower=1000, price_upper=500, location_radius=25)
    with pytest.raises(ValidationError):
        query.validate_constraints()


@pytest.mark.django_db
def test_price_constraint_allows_equal_prices(db):
    query = Query(price_lower=500, price_upper=500, location_radius=25)
    query.validate_constraints()  # should not raise


@pytest.mark.django_db
def test_price_constraint_allows_zero_prices(db):
    query = Query(price_lower=0, price_upper=0, location_radius=25)
    query.validate_constraints()  # should not raise


@pytest.mark.django_db
def test_section_category_constraint_rejects_both_set(section, category):
    query = Query(
        text="test",
        section=section,
        category=category,
        location_radius=25,
        price_lower=0,
        price_upper=0,
    )
    with pytest.raises(ValidationError):
        query.validate_constraints()


@pytest.mark.django_db
def test_section_category_constraint_allows_both_null(db):
    query = Query(text="test", section=None, category=None, location_radius=25, price_lower=0, price_upper=0)
    query.validate_constraints()  # should not raise


# --- Ad/AdDelivery split: pipeline state lives on AdDelivery, not Ad ---
# (see docs/archive/shipped/AD_DELIVERY_SPLIT.md)

def test_ad_status_choices():
    assert {c.value for c in AdStatus} == {
        "PENDING", "APPROVED", "REJECTED", "SUPPRESSED",
        "PRICE_CHANGED", "SENT", "FAILED",
    }


@pytest.mark.django_db
def test_delivery_default_status_is_pending(make_ad, make_delivery, query):
    ad = make_ad(query, bazos_id=999)
    ad.save()
    delivery = make_delivery(ad, query)
    assert delivery.status == AdStatus.PENDING


@pytest.mark.django_db
def test_delivery_send_attempts_defaults_to_zero(make_ad, make_delivery, query):
    ad = make_ad(query, bazos_id=999)
    ad.save()
    delivery = make_delivery(ad, query)
    assert delivery.send_attempts == 0


@pytest.mark.django_db
def test_delivery_filter_reason_is_optional(make_ad, make_delivery, query):
    ad = make_ad(query, bazos_id=999)
    ad.save()
    delivery = make_delivery(ad, query)
    assert delivery.filter_reason is None


@pytest.mark.django_db
def test_delivery_sent_at_is_optional(make_ad, make_delivery, query):
    ad = make_ad(query, bazos_id=999)
    ad.save()
    delivery = make_delivery(ad, query)
    assert delivery.sent_at is None


# ---------------------------------------------------------------------------
# Ad.admin_url — the self-link appended to every Discord notification
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_admin_url_is_absolute_and_points_at_the_change_page(make_ad, query, settings):
    settings.SITE_BASE_URL = "http://raspberrypi5.local:8000"
    ad = make_ad(query, bazos_id=14084)
    ad.save()

    assert ad.admin_url == f"http://raspberrypi5.local:8000/admin/bazos/ad/{ad.pk}/change/"


@pytest.mark.django_db
def test_admin_url_tracks_the_configured_base(make_ad, query, settings):
    """The host is configuration — the same row renders a different link per deployment."""
    ad = make_ad(query, bazos_id=14085)
    ad.save()

    settings.SITE_BASE_URL = "http://localhost:8000"
    local = ad.admin_url
    settings.SITE_BASE_URL = "http://pi.tail1234.ts.net:8000"
    tailnet = ad.admin_url

    assert local != tailnet
    assert local.endswith(f"/admin/bazos/ad/{ad.pk}/change/")
    assert tailnet.endswith(f"/admin/bazos/ad/{ad.pk}/change/")


@pytest.mark.django_db
def test_admin_url_tolerates_a_trailing_slash_on_the_base(make_ad, query, settings):
    """`reverse` returns a rooted path, so an unstripped base would yield `host//admin/`."""
    settings.SITE_BASE_URL = "http://localhost:8000/"
    ad = make_ad(query, bazos_id=14086)
    ad.save()

    assert "//admin" not in ad.admin_url
    assert ad.admin_url == f"http://localhost:8000/admin/bazos/ad/{ad.pk}/change/"


@pytest.mark.django_db
def test_admin_url_differs_from_the_marketplace_link(make_ad, query):
    """The two links in a notification must not collapse into the same URL."""
    ad = make_ad(query, bazos_id=14087)
    ad.save()

    assert ad.link == ad.url
    assert ad.admin_url != ad.link
