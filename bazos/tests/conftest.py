import re

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


# ---------------------------------------------------------------------------
# VCR cassette configuration
#
# See docs/refactor/E2E_REPLAY_TESTING_RESEARCH.md §4 for why each of these is
# set the way it is — every one of them was measured, and the defaults are
# wrong for this repo in at least three ways.
# ---------------------------------------------------------------------------

_RATING_CALL = re.compile(r"odeslatakci\('rating','(\d+)','(\d+)','([^']*)'\)")
_EMAIL_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")


def _scrub_seller_names(text: str) -> str:
    """Replace Bazos seller display names with a stable synthetic handle.

    The name is the one directly identifying field on a listing page. It is
    replaced with `Seller<email_id>` — derived from the opaque email id, so the
    same seller keeps the same handle across pages and cassettes and the
    seller-identity code still sees a consistent graph.

    The opaque email/phone ids themselves are deliberately kept: they are not
    emails or phone numbers (see CLAUDE.md's seller-identity section), they are
    what the parser is supposed to extract, and remapping them would make the
    publisher assertions test the scrub rather than the scraper.
    """
    def _replace(match: re.Match) -> str:
        email_id, phone_id, _name = match.groups()
        return f"odeslatakci('rating','{email_id}','{phone_id}','Seller{email_id}')"

    return _RATING_CALL.sub(_replace, text)


def scrub_response(response):
    """`before_record_response` hook: strip cookies and personal data.

    vcrpy's `filter_headers` only applies to *requests* — a response
    `Set-Cookie` is written to the cassette verbatim without this (measured:
    §4.5). Response bodies are not covered by any built-in filter at all.
    """
    headers = response.get("headers") or {}
    for name in list(headers):
        if name.lower() in {"set-cookie", "set-cookie2"}:
            headers.pop(name)

    body = (response.get("body") or {}).get("string")
    if body is not None:
        raw = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
        cleaned = _EMAIL_ADDRESS.sub("redacted@example.invalid", _scrub_seller_names(raw))
        response["body"]["string"] = cleaned.encode("utf-8") if isinstance(body, bytes) else cleaned
    return response


@pytest.fixture(scope="module")
def vcr_config():
    return {
        # record_mode is deliberately NOT set here: pytest-recording already
        # defaults to "none" (no network unless --record-mode is passed), and a
        # value in this dict silently overrides the --record-mode CLI flag,
        # making re-recording impossible.
        # Without this the body is stored as !!binary base64 of the gzip stream:
        # unreadable, ungreppable, unreviewable and impossible to scrub (§4.2).
        "decode_compressed_response": True,
        "filter_headers": ["cookie", "user-agent", "authorization"],
        "before_record_response": scrub_response,
        # Matching on host+port means cassettes MUST be recorded un-proxied: with
        # a proxy set, vcrpy sees the proxy's host:port, not bazos.cz (§4.6).
        "match_on": ["method", "scheme", "host", "port", "path", "query"],
    }
