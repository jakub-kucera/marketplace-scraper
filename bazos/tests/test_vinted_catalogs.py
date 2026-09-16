"""Tests for `manage.py create_vinted_catalogs` and the flight parser it rests on.

The fixture is a real slice of a live Vinted payload (real ids, titles and slugs),
reproducing the one structural trap the seeder has to survive: the tree is spread over
many `"catalogs"` arrays and the first one is a mid-tree slice, not the root.
"""
import json
from pathlib import Path
from unittest.mock import patch

import pytest
import requests

from bazos.management.commands.create_vinted_catalogs import collect, walk
from bazos.models import Marketplace, MarketplaceCategory, Query
from bazos.scraping.vinted import flight

FIXTURE = Path(__file__).parent / "fixtures" / "vinted_catalog_tree.txt"
COMMAND = "bazos.management.commands.create_vinted_catalogs"


@pytest.fixture
def payload():
    return FIXTURE.read_text(encoding="utf-8")


def run_command(payload_text):
    from django.core.management import call_command
    with patch("bazos.scraping.vinted.client.VintedClient.get_flight", return_value=payload_text):
        call_command("create_vinted_catalogs")


# --------------------------------------------------------------------------- parsing

def test_collect_finds_the_root_not_just_the_first_array(payload):
    """The regression this seeder exists to avoid.

    `"catalogs":[…]` occurs ~2,100 times in a real payload and the first is a mid-tree
    slice. Seeding from that alone silently misses entire branches — here, Elektronika.
    """
    nodes = collect(payload)
    assert 2994 in nodes, "root Elektronika missing — only the first array was read"
    assert nodes[2994] == ("Elektronika", "2994-electronics", None)


def test_collect_resolves_parents_from_structure(payload):
    nodes = collect(payload)
    assert nodes[3580][2] == 3564          # Notebooky -> Pocitace
    assert nodes[3564][2] == 2994          # Pocitace  -> Elektronika
    assert nodes[2994][2] is None          # Elektronika is a root


def test_collect_prefers_a_sighting_that_knows_the_parent(payload):
    """Notebooky appears twice: once in the parentless mid-tree slice, once under its
    real parent. The union has to keep the informative sighting regardless of order."""
    assert collect(payload)[3580][2] == 3564


def test_walk_ignores_malformed_nodes():
    nodes = list(walk([
        {"id": 1, "title": "Good", "url": "/catalog/1-good"},
        {"id": 2},                       # no title
        {"title": "No id"},
        "not a dict",
        {"id": 3, "title": "", "url": ""},   # empty title
    ]))
    assert [n[0] for n in nodes] == [1]


def test_slug_parsed_from_url(payload):
    assert collect(payload)[3580][1] == "3580-laptops"


# --------------------------------------------------------------------------- seeding

@pytest.mark.django_db
def test_seeds_the_tree(payload):
    run_command(payload)
    laptops = MarketplaceCategory.objects.get(
        marketplace=Marketplace.VINTED, external_id="3580"
    )
    assert laptops.name == "Notebooky"
    assert laptops.slug == "3580-laptops"
    assert laptops.path == "Elektronika > Počítače a příslušenství > Notebooky"


@pytest.mark.django_db
def test_is_idempotent(payload):
    run_command(payload)
    first = set(MarketplaceCategory.objects.values_list("external_id", flat=True))
    count = MarketplaceCategory.objects.count()

    run_command(payload)

    assert MarketplaceCategory.objects.count() == count
    assert set(MarketplaceCategory.objects.values_list("external_id", flat=True)) == first
    assert MarketplaceCategory.objects.get(external_id="3580").path.startswith("Elektronika")


@pytest.mark.django_db
def test_rerun_repairs_a_broken_parent(payload):
    """Parents are written in a second pass, so a row whose parent was cleared by hand
    (or by an older partial seed) is fixed by re-running rather than left dangling."""
    run_command(payload)
    laptops = MarketplaceCategory.objects.get(external_id="3580")
    laptops.parent = None
    laptops.save(update_fields=["parent"])

    run_command(payload)

    laptops.refresh_from_db()
    assert laptops.parent.external_id == "3564"


@pytest.mark.django_db
def test_empty_payload_writes_nothing_and_raises(payload):
    """A shape change must not look like a successful seed of zero categories."""
    with pytest.raises(RuntimeError, match="no catalog nodes"):
        run_command("1:{}\n")
    assert MarketplaceCategory.objects.count() == 0


@pytest.mark.django_db
def test_retired_node_is_kept_and_reported(payload):
    """Never delete: the ids live in Query.extra_params, and stranding them is the whole
    reason this is not a Query FK.

    Asserted on the logger call rather than caplog — the `bazos` logger has
    propagate=False (settings.py), so its records never reach caplog's root handler.
    """
    MarketplaceCategory.objects.create(
        marketplace=Marketplace.VINTED, external_id="999999", name="Retired",
    )
    with patch(f"{COMMAND}.logger") as logger:
        run_command(payload)

    assert MarketplaceCategory.objects.filter(external_id="999999").exists()
    warned = " ".join(str(call) for call in logger.warning.call_args_list)
    assert "999999" in warned


@pytest.mark.django_db
def test_query_referencing_a_retired_node_is_named(payload):
    Query.objects.create(
        text="macbook", marketplace=Marketplace.VINTED,
        price_lower=0, price_upper=0, extra_params={"catalog_ids": [999999]},
    )
    MarketplaceCategory.objects.create(
        marketplace=Marketplace.VINTED, external_id="999999", name="Retired",
    )
    with patch(f"{COMMAND}.logger") as logger:
        run_command(payload)

    warned = " ".join(str(call) for call in logger.warning.call_args_list)
    assert "retired Vinted catalog id" in warned


@pytest.mark.django_db
def test_does_not_touch_other_marketplaces(payload):
    sbazar = MarketplaceCategory.objects.create(
        marketplace=Marketplace.SBAZAR, external_id="3580", name="Nářadí",
    )
    run_command(payload)
    sbazar.refresh_from_db()
    assert sbazar.name == "Nářadí"


# --------------------------------------------------------------------------- flight

def test_balanced_slice_survives_quotes_and_brackets():
    """The single most breakage-prone thing in the Vinted work: real listing titles carry
    `"`, `[`, `{` and backslashes, so a regex cannot find the end of the value."""
    text = '"items":[{"title":"MacBook Pro 13\\" Retina [A1502] {x}","id":1}] tail'
    value = flight.get(text, "items")
    assert value == [{"title": 'MacBook Pro 13" Retina [A1502] {x}', "id": 1}]


def test_balanced_slice_returns_none_on_truncation():
    assert flight.balanced_slice('[{"a": 1}', 0) is None


def test_decode_unwraps_html_chunks():
    html = r'<script>self.__next_f.push([1,"{\"a\":1}"])</script>'
    assert flight.decode(html) == '{"a":1}'


def test_decode_passes_raw_payload_through():
    assert flight.decode('3:{"a":1}') == '3:{"a":1}'


# --------------------------------------------------------------------------- transport

def test_get_flight_forces_utf8_decoding():
    """Regression: Vinted serves `text/x-component` with no charset, so requests falls
    back to ISO-8859-1 (RFC 2616) while the bytes are UTF-8.

    Left alone this mojibakes every accented title — "Počítače" became "PoÄÃ­taÄe" when
    seeding against the live site — which would corrupt Ad.name/short_description and
    every keyword match built on them. A UTF-8 fixture file cannot reproduce it, so the
    check has to be on the response object.
    """
    from bazos.scraping.vinted.client import VintedClient

    body = '"catalogs":[{"id":3580,"title":"Počítače"}]'
    response = requests.Response()
    response.status_code = 200
    response._content = body.encode("utf-8")
    response.headers["Content-Type"] = "text/x-component"   # no charset — the trap
    # What the real adapter does for a charset-less text/* response (RFC 2616). Set here
    # explicitly because a hand-built Response never runs that guess, and leaving it None
    # would let charset detection quietly rescue the test and prove nothing.
    response.encoding = "ISO-8859-1"
    assert "Počítače" not in response.text, "precondition: latin-1 mangles the payload"

    client = VintedClient()
    client._bootstrapped = True
    with patch.object(client.session, "get", return_value=response):
        assert "Počítače" in client.get_flight("/catalog")


def test_iter_values_yields_every_occurrence():
    text = '"catalogs":[1] then "catalogs":[2,3]'
    assert list(flight.iter_values(text, "catalogs")) == [[1], [2, 3]]


# --------------------------------------------------------------------------- client

def _ok(body: str = '1:{"a":1}') -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response._content = body.encode("utf-8")
    response.headers["Content-Type"] = "text/x-component"
    return response


def test_bootstrap_fetches_the_site_root_once():
    """The root GET is what sets access_token_web; repeating it per request would double
    the request count for no gain."""
    from bazos.scraping.vinted.client import VintedClient

    client = VintedClient()
    with patch.object(client.session, "get", return_value=_ok()) as get:
        client.bootstrap()
        client.bootstrap()

    assert get.call_count == 1
    assert get.call_args[0][0] == "https://www.vinted.cz/"


def test_bootstrap_raises_on_an_error_status():
    """"Cannot reach Vinted at all" is a genuine query failure and belongs on QueryRun —
    deliberately not swallowed here, unlike the per-ad detail failures."""
    from bazos.scraping.vinted.client import VintedClient

    failed = requests.Response()
    failed.status_code = 503
    client = VintedClient()
    with patch.object(client.session, "get", return_value=failed):
        with pytest.raises(requests.HTTPError):
            client.bootstrap()


def test_get_flight_bootstraps_first():
    from bazos.scraping.vinted.client import VintedClient

    client = VintedClient()
    with patch.object(client.session, "get", return_value=_ok()) as get:
        client.get_flight("/catalog")
    assert get.call_count == 2, "did not bootstrap before fetching"
    assert get.call_args_list[0][0][0].endswith("/")


def test_get_flight_repeats_bracket_params():
    """`catalog[]` repeats, which is why params are pairs rather than a dict."""
    from bazos.scraping.vinted.client import VintedClient

    client = VintedClient()
    client._bootstrapped = True
    with patch.object(client.session, "get", return_value=_ok()) as get:
        client.get_flight("/catalog", [("catalog[]", 3580), ("catalog[]", 3581)])

    url = get.call_args[0][0]
    assert url.count("catalog%5B%5D=") == 2
    assert "3580" in url and "3581" in url


def test_get_flight_sends_the_rsc_header_and_a_browser_user_agent():
    """Without a browser UA the request is served a DataDome interstitial; RSC:1 is what
    returns the payload without the HTML shell."""
    from bazos.scraping.vinted.client import VintedClient

    client = VintedClient()
    client._bootstrapped = True
    with patch.object(client.session, "get", return_value=_ok()) as get:
        client.get_flight("/catalog")

    headers = get.call_args[1]["headers"]
    assert headers["RSC"] == "1"
    assert "Mozilla/5.0" in headers["User-Agent"]


def test_get_flight_omits_the_query_string_when_there_are_no_params():
    from bazos.scraping.vinted.client import VintedClient

    client = VintedClient()
    client._bootstrapped = True
    with patch.object(client.session, "get", return_value=_ok()) as get:
        client.get_flight("/items/1-x")
    assert get.call_args[0][0] == "https://www.vinted.cz/items/1-x"


def test_base_url_trailing_slash_is_normalised():
    from bazos.scraping.vinted.client import VintedClient

    assert VintedClient("https://www.vinted.sk/").base_url == "https://www.vinted.sk"


# --------------------------------------------------------------------------- flight edges

def test_scanning_continues_past_a_scalar_value():
    """Regression: the same key name is reused across the payload, so an occurrence whose
    value is a scalar must be skipped rather than ending the scan. One stray
    `"attributes":"..."` used to hide every real attributes block after it."""
    text = '"catalogs":"not a list" then "catalogs":[{"id":1}]'
    assert list(flight.iter_values(text, "catalogs")) == [[{"id": 1}]]


def test_scanning_continues_past_a_truncated_value():
    text = '"catalogs":[{"id": then "catalogs":[{"id":2}]'
    assert list(flight.iter_values(text, "catalogs")) == [[{"id": 2}]]


def test_get_returns_none_for_a_missing_key():
    assert flight.get('{"a":1}', "nope") is None


def test_decode_skips_an_undecodable_chunk_but_keeps_the_rest():
    """A chunk that matches the script pattern but is not a decodable JSON string is
    dropped, not raised on — the payload is a stream and values are found by key, so
    losing one chunk is survivable. (A chunk whose *pattern* is malformed is not modelled:
    Next.js always emits well-formed string literals, and the caller's "did anything
    parse?" check covers the case where nothing does.)"""
    def push(literal: str) -> str:
        return f"<script>self.__next_f.push([1,{literal}])</script>"

    html = (
        push(json.dumps('{"a":1}'))          # a well-formed JSON string literal
        + push('"bad \\e escape"')           # matches the pattern, fails json.loads
        + push(json.dumps('{"b":2}'))
    )
    decoded = flight.decode(html)
    assert '{"a":1}' in decoded, "a valid chunk before the bad one was lost"
    assert '{"b":2}' in decoded, "a valid chunk after the bad one was lost"
    assert "bad" not in decoded


def test_balanced_slice_rejects_a_non_container_start():
    assert flight.balanced_slice('"just a string"', 0) is None


def test_items_reads_the_wrapper_object():
    """The payload nests as {"items": {"items": [...], "pagination": {...}}}."""
    text = '"items":{"items":[{"id":1}],"pagination":{"total_pages":1}}'
    assert flight.items(text) == [{"id": 1}]


def test_items_returns_empty_when_nothing_parses():
    assert flight.items("not a payload at all") == []


def test_items_ignores_non_dict_rows():
    assert flight.items('"items":[{"id":1},"junk",null]') == [{"id": 1}]


def test_scanning_continues_past_a_balanced_but_invalid_value():
    """Brackets can balance while the contents are not JSON — the RSC stream mixes
    fragments, so a balanced slice is a candidate, not a guarantee."""
    text = '"catalogs":[{not json at all}] then "catalogs":[{"id":3}]'
    assert list(flight.iter_values(text, "catalogs")) == [[{"id": 3}]]
