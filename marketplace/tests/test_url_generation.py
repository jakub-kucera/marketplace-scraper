import itertools
from urllib.parse import parse_qs, urlparse

import pytest

from marketplace.const import BAZOS_URL, PAGE_SIZE
from marketplace.scraping.bazos.bazos_scraper import BazosScraper


@pytest.mark.django_db
def test_get_query_url_dict_zero_prices_become_empty_string(query):
    query.price_lower = 0
    query.price_upper = 0
    params = BazosScraper.get_query_url_dict(query)
    assert params["cenaod"] == ""
    assert params["cenado"] == ""


@pytest.mark.django_db
def test_get_query_url_dict_nonzero_prices_are_passed_through(query):
    query.price_lower = 500
    query.price_upper = 2000
    params = BazosScraper.get_query_url_dict(query)
    assert params["cenaod"] == 500
    assert params["cenado"] == 2000


@pytest.mark.django_db
def test_get_query_url_dict_contains_query_text(query):
    params = BazosScraper.get_query_url_dict(query)
    assert params["hledat"] == query.text


@pytest.mark.django_db
def test_get_query_url_dict_contains_location(query):
    params = BazosScraper.get_query_url_dict(query)
    assert params["hlokalita"] == query.location_center
    assert params["humkreis"] == str(query.location_radius)


@pytest.mark.django_db
def test_create_url_category_first_page_starts_at_zero(query):
    first_url = next(BazosScraper.create_url_category(query))
    path = urlparse(first_url).path
    assert "/0/" in path


@pytest.mark.django_db
def test_create_url_category_paginates_by_page_size(query):
    urls = list(itertools.islice(BazosScraper.create_url_category(query), 3))
    assert f"/{PAGE_SIZE}/" in urls[1]
    assert f"/{PAGE_SIZE * 2}/" in urls[2]


@pytest.mark.django_db
def test_create_url_category_uses_query_base_url(query):
    first_url = next(BazosScraper.create_url_category(query))
    assert first_url.startswith(query.url)


@pytest.mark.django_db
def test_create_url_general_first_page_has_crz_zero(query):
    query.category = None
    query.section = None
    query.save()
    first_url = next(BazosScraper.create_url_general(query))
    qs = parse_qs(urlparse(first_url).query)
    assert qs["crz"] == ["0"]


@pytest.mark.django_db
def test_create_url_general_paginates_crz_by_page_size(query):
    query.category = None
    query.section = None
    query.save()
    urls = list(itertools.islice(BazosScraper.create_url_general(query), 3))
    assert parse_qs(urlparse(urls[1]).query)["crz"] == [str(PAGE_SIZE)]
    assert parse_qs(urlparse(urls[2]).query)["crz"] == [str(PAGE_SIZE * 2)]


@pytest.mark.django_db
def test_create_url_general_targets_the_search_endpoint(query):
    """A section-less, category-less Query must search, not hit the bare origin.

    This asserted `startswith(BAZOS_BASE_URL)` until 2026-08-23, which was true of
    the broken URL (`https://bazos.cz?hledat=...`) *and* of the fixed one, since
    BAZOS_URL starts with BAZOS_BASE_URL. Bazos redirects the bare-origin form to
    the homepage and drops the query string, so the scraper silently found no ads.
    Asserting on the path is what makes the difference visible.
    """
    query.category = None
    query.section = None
    query.save()
    first_url = next(BazosScraper.create_url_general(query))
    assert first_url.startswith(BAZOS_URL)
    assert urlparse(first_url).path == "/search.php"
