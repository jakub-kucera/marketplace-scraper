"""Transport-level tests for BazosScraper, replayed from recorded cassettes.

Every other scraper test in this suite stops *above* the transport: it either
patches `run_query` wholesale or hands `_parse_product` a hand-built string. So
nothing covered `run_request`, `get_page_products`, pagination termination, the
403 path, gzip/charset decoding, or the relative→absolute URL promotion that
depends on the response's final URL. This module covers exactly that seam, by
replaying real bazos.cz responses through the real requests/urllib3/BeautifulSoup
stack. The only fake thing is the socket.

Re-recording
------------
Cassettes live in `bazos/tests/cassettes/test_bazos_scraper_transport/`. To
refresh them against the live site:

    rm -rf bazos/tests/cassettes/test_bazos_scraper_transport
    poetry run pytest bazos/tests/test_bazos_scraper_transport.py --record-mode=once

The session MUST be un-proxied when recording (no Tor): with a proxy configured
vcrpy records the *proxy's* host:port rather than bazos.cz, and replay then fails
every host/port match. See docs/refactor/E2E_REPLAY_TESTING_RESEARCH.md §4.6.

`blacklisted_403.yaml` is hand-written, not recorded — you cannot summon a ban on
demand.
"""
from itertools import islice
from pathlib import Path

import pytest
import requests
import vcr
import yaml

from bazos.tests import conftest

from bazos.exceptions import BazosBlacklistedError
from bazos.models import Ad, EmailPublisher, PhonePublisher, Query
from bazos.scraping.bazos.bazos_scraper import BazosScraper

MANUAL_CASSETTES = Path(__file__).parent / "cassettes" / "manual"


@pytest.fixture(autouse=True)
def no_page_sleep(monkeypatch):
    """`run_query` sleeps uniform(2, 5) between pages — 15 s for a 3-page cassette."""
    monkeypatch.setattr("bazos.scraping.bazos.bazos_scraper.sleep", lambda _seconds: None)


@pytest.fixture
def scraper():
    """A scraper on a plain, un-proxied session — see the module docstring."""
    return BazosScraper(requests.Session())


@pytest.fixture
def notebook_query(category):
    """Narrow enough that page 2 comes back empty, so pagination terminates."""
    return Query.objects.create(
        text="thinkpad x230",
        category=category,
        location_center="",
        location_radius=25,
        price_lower=0,
        price_upper=0,
        new_query=False,
    )


@pytest.fixture
def general_query(db):
    """No section and no category — the whole-site search path (§1a)."""
    return Query.objects.create(
        text="macbook",
        location_center="",
        location_radius=25,
        price_lower=0,
        price_upper=0,
        new_query=False,
    )


# ---------------------------------------------------------------------------
# Parsing a real page
# ---------------------------------------------------------------------------

@pytest.mark.vcr
@pytest.mark.django_db
def test_run_query_parses_ads_from_a_real_page(scraper, notebook_query):
    ads = list(islice(scraper.run_query(notebook_query), 5))

    assert ads, "no ads parsed from a live-recorded page — parser drift"
    assert all(isinstance(ad, Ad) for ad in ads)


@pytest.mark.vcr
@pytest.mark.django_db
def test_parsed_ads_have_absolute_urls(scraper, notebook_query):
    """`urljoin(response.url, ...)` promotes the relative href — untestable off-transport."""
    ads = list(islice(scraper.run_query(notebook_query), 5))

    assert ads
    for ad in ads:
        assert ad.url.startswith("https://"), ad.url
        assert "/inzerat/" in ad.url


@pytest.mark.vcr
@pytest.mark.django_db
def test_parsed_ads_have_the_core_fields_populated(scraper, notebook_query):
    ads = list(islice(scraper.run_query(notebook_query), 5))

    assert ads
    for ad in ads:
        assert ad.external_id
        assert ad.name.strip()
        assert ad.price_raw.strip()
        assert ad.location.strip()
        assert ad.publish_date is not None
        assert ad.view_count is not None


@pytest.mark.vcr
@pytest.mark.django_db
def test_publisher_rows_are_resolved_from_the_page(scraper, notebook_query):
    ads = list(islice(scraper.run_query(notebook_query), 5))

    assert ads
    linked = [ad for ad in ads if ad.email_publisher or ad.phone_publisher]
    assert linked, "no ad on the page resolved to a publisher"
    assert EmailPublisher.objects.exists() or PhonePublisher.objects.exists()


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

@pytest.mark.vcr
@pytest.mark.django_db
def test_run_query_stops_after_a_page_with_no_ads(scraper, notebook_query):
    """`if not products: break` — the loop that carries a "looks like it is not
    working" TODO. This pins how many requests the query actually costs."""
    list(scraper.run_query(notebook_query))

    assert scraper.sent_requests_count == 2


@pytest.mark.vcr
@pytest.mark.django_db
def test_first_page_404_is_still_parsed(scraper, notebook_query):
    """Bazos serves `/notebook/0/?...` with a 404 status but the correct listing body.

    Measured 2026-08-23: the content is byte-identical in ad terms to
    `/notebook/?...`, which returns 200. `run_request` only special-cases 403, so
    this works today — but it means adding a `raise_for_status()` or a
    `status_code == 200` guard would silently break page 1 of *every* category
    query. This test is here so that change fails loudly instead.
    """
    ads = list(islice(scraper.run_query(notebook_query), 1))

    assert ads, "page 1 returned no ads — has the 404-with-body behaviour changed?"


# ---------------------------------------------------------------------------
# Whole-site search — the §1a regression
# ---------------------------------------------------------------------------

@pytest.mark.vcr
@pytest.mark.django_db
def test_general_search_returns_ads(scraper, general_query):
    """A section-less, category-less Query must actually find ads.

    Until 2026-08-23 this built `https://bazos.cz?hledat=...`, which Bazos
    redirects to the homepage with the query string dropped, so the query
    silently scraped nothing on every pass. See
    docs/refactor/E2E_REPLAY_TESTING_RESEARCH.md §1a.
    """
    ads = list(islice(scraper.run_query(general_query), 5))

    assert ads, "whole-site search parsed zero ads"
    assert all(ad.external_id for ad in ads)


# ---------------------------------------------------------------------------
# Blacklisting
# ---------------------------------------------------------------------------

@pytest.mark.vcr
@pytest.mark.django_db
def test_check_blacklisted_is_false_on_a_normal_response(scraper):
    assert scraper.check_blacklisted() is False


@pytest.mark.django_db
def test_run_query_raises_on_403(scraper, notebook_query):
    """Hand-written cassette: a ban cannot be recorded on demand."""
    cassette = MANUAL_CASSETTES / "blacklisted_403.yaml"
    with vcr.use_cassette(str(cassette), record_mode="none", match_on=["method", "path"]):
        with pytest.raises(BazosBlacklistedError):
            list(scraper.run_query(notebook_query))


@pytest.mark.django_db
def test_check_blacklisted_is_true_on_403(scraper):
    cassette = MANUAL_CASSETTES / "blacklisted_403.yaml"
    with vcr.use_cassette(str(cassette), record_mode="none", match_on=["method", "path"]):
        assert scraper.check_blacklisted() is True


# ---------------------------------------------------------------------------
# Detail page
# ---------------------------------------------------------------------------

@pytest.mark.vcr
@pytest.mark.django_db
def test_load_full_description_populates_the_field(scraper, notebook_query):
    ads = list(islice(scraper.run_query(notebook_query), 1))
    ad = ads[0]
    assert ad.full_description is None

    scraper.load_full_description(ad)

    assert ad.full_description
    assert ad.full_description.strip()


# ---------------------------------------------------------------------------
# Cassette hygiene
#
# The patterns are imported from conftest rather than restated here, on purpose:
# the first version of this guard restated them, drifted from the scrubber, and
# passed while a real seller name sat in a committed cassette. A guard that can
# only confirm what the scrubber already did is worse than no guard.
# ---------------------------------------------------------------------------

CASSETTE_DIR = Path(__file__).parent / "cassettes"


def _cassette_files():
    return sorted(CASSETTE_DIR.rglob("*.yaml"))


def _decoded_bodies(cassette: Path) -> str:
    """Concatenated response bodies, decoded out of the YAML.

    Never scan the raw file text. PyYAML folds long scalars — measured at 444
    mid-token line breaks in a single cassette — so a regex over the file misses
    matches that plainly exist in the data. That is precisely how the first
    version of this test reported a clean cassette that contained a seller's name.
    """
    data = yaml.safe_load(cassette.read_text(encoding="utf-8", errors="replace"))
    bodies = []
    for interaction in data.get("interactions", []):
        body = (interaction.get("response") or {}).get("body", {}).get("string")
        if body is None:
            continue
        bodies.append(body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body)
    return "\n".join(bodies)


def test_cassettes_exist():
    assert _cassette_files(), "no cassettes committed — the transport tests are vacuous"


@pytest.mark.parametrize("cassette", _cassette_files(), ids=lambda p: p.name)
def test_cassette_carries_no_personal_data(cassette):
    """Mirrors conftest.scrub_body exactly — same patterns, opposite direction.

    Ad bodies are public listing text and are kept verbatim on purpose. Seller
    display names, email addresses and phone numbers are not.
    """
    body = _decoded_bodies(cassette)

    leaked = {e for e in conftest._EMAIL_ADDRESS.findall(body) if e != conftest.REDACTED_EMAIL}
    assert not leaked, f"{cassette.name} leaks email addresses: {sorted(leaked)[:5]}"

    phones = {p for p in conftest._PHONE_NUMBER.findall(body) if p != conftest.REDACTED_PHONE}
    assert not phones, f"{cassette.name} leaks phone numbers: {sorted(phones)[:5]}"

    for match in conftest._RATING_SPAN.finditer(body):
        handle = f"Seller{match.group('email')}"
        assert match.group("name") == handle, (
            f"{cassette.name} leaks a seller name in the rating onclick: {match.group('name')!r}"
        )
        visible = match.group("text").strip()
        assert visible == handle or visible in conftest._RATING_SPAN_UI_LABELS, (
            f"{cassette.name} leaks a seller name as visible text: {visible!r}. "
            f"If Bazos added a UI label, add it to _RATING_SPAN_UI_LABELS in conftest."
        )


@pytest.mark.parametrize("cassette", _cassette_files(), ids=lambda p: p.name)
def test_cassette_is_human_readable(cassette):
    """`decode_compressed_response=True` must stay on, or bodies become base64 gzip."""
    raw = cassette.read_text(encoding="utf-8", errors="replace")
    assert "!!binary" not in raw, (
        f"{cassette.name} stored a binary body — is decode_compressed_response still set?"
    )


@pytest.mark.parametrize("cassette", _cassette_files(), ids=lambda p: p.name)
def test_cassette_content_length_matches_the_stored_body(cassette):
    """Scrubbing changes body length after vcrpy has already fixed the header.

    Inert while vcrpy's stub serves the stored string directly, but a stale value
    would truncate a replayed page for any client that honours it.
    """
    data = yaml.safe_load(cassette.read_text(encoding="utf-8", errors="replace"))
    for interaction in data.get("interactions", []):
        response = interaction["response"]
        headers = {k.lower(): v for k, v in (response.get("headers") or {}).items()}
        if "content-length" not in headers:
            continue
        body = response["body"]["string"]
        actual = len(body.encode("utf-8")) if isinstance(body, str) else len(body)
        assert int(headers["content-length"][0]) == actual, (
            f"{cassette.name}: Content-Length {headers['content-length'][0]} != body {actual}"
        )
