import pytest
from django.core.exceptions import ValidationError

from bazos.const import BAZOS_BASE_URL
from bazos.models import Ad, AdStatus, Category, Query, Section


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


# --- Stage 1: Ad status fields ---

def test_ad_status_choices():
    assert {c.value for c in AdStatus} == {
        "PENDING", "APPROVED", "REJECTED", "SUPPRESSED",
        "PRICE_CHANGED", "SENT", "FAILED",
    }


@pytest.mark.django_db
def test_ad_default_status_is_pending(make_ad, query):
    ad = make_ad(query, bazos_id=999)
    ad.save()
    assert ad.status == AdStatus.PENDING


@pytest.mark.django_db
def test_ad_send_attempts_defaults_to_zero(make_ad, query):
    ad = make_ad(query, bazos_id=999)
    ad.save()
    assert ad.send_attempts == 0


@pytest.mark.django_db
def test_ad_filter_reason_is_optional(make_ad, query):
    ad = make_ad(query, bazos_id=999)
    ad.save()
    assert ad.filter_reason is None


@pytest.mark.django_db
def test_ad_sent_at_is_optional(make_ad, query):
    ad = make_ad(query, bazos_id=999)
    ad.save()
    assert ad.sent_at is None
