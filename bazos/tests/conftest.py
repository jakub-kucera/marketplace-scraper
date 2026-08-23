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

# The seller's name appears TWICE on a Bazos detail page: once as the 4th
# argument of the rating onclick, and once as the span's visible text. Scrubbing
# only the argument leaves the real name sitting in the cassette — which is
# exactly what happened on the first pass at this.
#
# The catch is that the same onclick is also attached to spans whose visible text
# is a UI label, and `BazosScraper._parse_action_args` finds its span *by that
# text* — rewriting those would break the parser outright.
#
# So the visible text is default-DENY: everything is replaced with the synthetic
# handle unless it is a known Bazos UI label. Matching on "text == the name in the
# onclick" would read more naturally, but it fails open twice over — it misses any
# rendering that differs from the argument (truncated, re-cased), and it cannot
# repair a cassette whose onclick has already been scrubbed, since the name it
# needed to compare against is gone. A redaction control should fail closed.
#
# If Bazos adds a label, the hygiene test fails and it gets added here — loudly.
_RATING_SPAN_UI_LABELS = frozenset({
    "Ohodnotit uživatele",
    "Všechny inzeráty a hodnocení uživatele",
})
_RATING_SPAN = re.compile(
    r"odeslatakci\('rating','(?P<email>\d+)','(?P<phone>\d+)','(?P<name>[^']*)'\)"
    r"(?P<mid>;return false;\"[^>]*>)(?P<text>[^<]*)(?P<close></span>)"
)
# Fallback for any rating call not followed by a closing span.
_RATING_CALL = re.compile(r"odeslatakci\('rating','(\d+)','(\d+)','([^']*)'\)")

_EMAIL_ADDRESS = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]{2,}")

# Czech mobile numbers (9 digits, leading 6 or 7), with or without a +420/00420
# prefix and with any of the usual separators.
#
# Deliberately NOT matching bare 9-digit landlines (leading 2-5): Bazos ad ids are
# also 9 digits and every one in these cassettes starts with 2, so a wider pattern
# would corrupt the ids the parser reads. Landlines are still caught when they
# carry an explicit country prefix. This boundary is stated rather than silent, and
# the hygiene test in test_bazos_scraper_transport.py asserts exactly this pattern
# — the scrub and the assertion must cover the same surface, or a re-record
# produces a red test on a file that is already on disk.
_PHONE_NUMBER = re.compile(
    r"(?<![\d/])(?:(?:\+|00)420[\s./-]?)?[67]\d{2}[\s./-]?\d{3}[\s./-]?\d{3}(?!\d)"
)

REDACTED_EMAIL = "redacted@example.invalid"
REDACTED_PHONE = "000000000"


def _scrub_seller_names(text: str) -> str:
    """Replace Bazos seller display names with a stable synthetic handle.

    The name is the one directly identifying field on a listing page. It becomes
    `Seller<email_id>` — derived from the opaque email id, so the same seller keeps
    the same handle across pages and cassettes and the seller-identity code still
    sees a consistent graph.

    The opaque email/phone ids themselves are deliberately kept: they are not
    emails or phone numbers (see CLAUDE.md's seller-identity section), they are
    what the parser is supposed to extract, and remapping them would make the
    publisher assertions test the scrub rather than the scraper.
    """
    def _replace_span(match: re.Match) -> str:
        email_id = match.group("email")
        handle = f"Seller{email_id}"
        visible = match.group("text")
        keep = visible.strip() in _RATING_SPAN_UI_LABELS
        return (
            f"odeslatakci('rating','{email_id}','{match.group('phone')}','{handle}')"
            f"{match.group('mid')}"
            f"{visible if keep else handle}"
            f"{match.group('close')}"
        )

    def _replace_call(match: re.Match) -> str:
        email_id, phone_id, _name = match.groups()
        return f"odeslatakci('rating','{email_id}','{phone_id}','Seller{email_id}')"

    return _RATING_CALL.sub(_replace_call, _RATING_SPAN.sub(_replace_span, text))


def scrub_body(text: str) -> str:
    """Every body-level redaction, in one place, so the hygiene test can mirror it."""
    text = _scrub_seller_names(text)
    text = _EMAIL_ADDRESS.sub(REDACTED_EMAIL, text)
    return _PHONE_NUMBER.sub(REDACTED_PHONE, text)


def scrub_response(response):
    """`before_record_response` hook: strip cookies and personal data.

    vcrpy's `filter_headers` only applies to *requests* — a response `Set-Cookie`
    is written to the cassette verbatim without this (measured: §4.5). Response
    bodies are not covered by any built-in filter at all.
    """
    headers = response.get("headers") or {}
    for name in list(headers):
        if name.lower() in {"set-cookie", "set-cookie2"}:
            headers.pop(name)

    body = (response.get("body") or {}).get("string")
    if body is not None:
        is_bytes = isinstance(body, bytes)
        cleaned = scrub_body(body.decode("utf-8", errors="replace") if is_bytes else body)
        encoded = cleaned.encode("utf-8")
        response["body"]["string"] = encoded if is_bytes else cleaned
        # vcrpy fixes Content-Length when it decodes the response, but that runs
        # *before* this hook, and redaction changes the body length. Left stale it
        # would truncate a replayed page for any client that honours the header.
        for name in list(headers):
            if name.lower() == "content-length":
                headers[name] = [str(len(encoded))]
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
