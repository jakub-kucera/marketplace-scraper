"""End-to-end pipeline test: scrape -> filter -> send, replayed from a cassette.

Every stage of the pipeline is well covered in isolation, but nothing exercised
them as one flow. This module seeds two Query rows against the same Bazos
search, runs the real scraper against recorded HTTP, then drives the real
`run_filter --once` and `run_sender --once`, and compares the whole resulting
state — Ad rows, per-query AdDelivery statuses, and the exact Discord message
text — against a committed snapshot.

The two queries share a search but differ in filter config, so the snapshot also
pins the Ad/AdDelivery split: one global Ad row, two independent deliveries,
which may legitimately end in different states.

Nothing reaches the network: HTTP is replayed by vcrpy and DiscordSender._send
is captured. See test_bazos_scraper_transport.py for how to re-record, and
docs/refactor/E2E_REPLAY_TESTING_RESEARCH.md §6 for the determinism rules these
snapshots depend on.

    UPDATE_SNAPSHOTS=1 pytest bazos/tests/test_pipeline_e2e.py   # regenerate
"""
import json
import os
from pathlib import Path

import pytest
import requests
from django.core.management import call_command

from bazos.models import Ad, AdDelivery, AdStatus, Query
from bazos.scraping.bazos_query_runner import BazosQueryRunner
from senders.models import Discord
from senders.services.discord_sender import DiscordSender

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"

# Real want-to-buy ads ("KOUPIM") and spare parts ("Displej") on the recorded
# page — a filter config someone would actually write, and one that splits the
# page rather than accepting or rejecting all of it.
BLOCKLIST = ["koupim", "displej"]


@pytest.fixture(autouse=True)
def no_page_sleep(monkeypatch):
    monkeypatch.setattr("bazos.scraping.bazos.bazos_scraper.sleep", lambda _seconds: None)


@pytest.fixture
def discord(db):
    return Discord.objects.create(channel_name="deals", url="https://discord.test/webhook")


def _make_query(category, discord, **overrides):
    defaults = dict(
        text="thinkpad x230",
        category=category,
        location_center="",
        location_radius=25,
        price_lower=0,
        price_upper=0,
        new_query=False,
        ignore_first_run=False,
        load_full_description=False,
        sender=discord,
    )
    defaults.update(overrides)
    return Query.objects.create(**defaults)


@pytest.fixture
def permissive_query(category, discord):
    return _make_query(category, discord)


@pytest.fixture
def blocklist_query(category, discord):
    return _make_query(category, discord, filter_blocklist=BLOCKLIST)


@pytest.fixture
def sent_messages(monkeypatch):
    """Capture fully rendered Discord messages instead of posting them.

    Patching `_send` rather than `from_model` means the snapshot covers the real
    formatting path — wrap_multi_line, the link wrapper, and Ad.message with its
    seller-ad-counts summary — and incidentally skips its uniform(0.5, 2) sleep.
    """
    captured: list[str] = []
    monkeypatch.setattr(DiscordSender, "_send", lambda self, message: captured.append(message))
    return captured


def run_pipeline(queries, sent_messages):
    """One full pass: scrape every query, then filter, then send."""
    session = requests.Session()   # un-proxied on purpose — see §4.6
    for query in queries:
        BazosQueryRunner(query, session).run()
    call_command("run_filter", once=True)
    call_command("run_sender", once=True)
    return sent_messages


# ---------------------------------------------------------------------------
# Snapshot machinery
# ---------------------------------------------------------------------------

def snapshot_state(query_labels: dict[int, str], sent_messages: list[str]) -> dict:
    """Serialise the pipeline's result, excluding everything non-deterministic.

    Wall-clock columns (created/modified/sent_at) are reduced to booleans and
    primary keys are dropped: both change per run without meaning anything.
    """
    ads = [
        {
            "external_id": ad.external_id,
            "marketplace": ad.marketplace,
            "name": ad.name,
            "price_raw": ad.price_raw,
            "price": ad.price,
            "price_type": ad.price_type,
            "topped": ad.topped,
            "location": ad.location,
            "url": ad.url,
            "publish_date": ad.publish_date.isoformat() if ad.publish_date else None,
            "view_count": ad.view_count,
            "short_description": ad.short_description,
            "publisher_name": ad.publisher_name,
            "email_publisher": ad.email_publisher.bazos_id if ad.email_publisher else None,
            "phone_publisher": ad.phone_publisher.bazos_id if ad.phone_publisher else None,
        }
        for ad in Ad.objects.select_related("email_publisher", "phone_publisher").order_by("external_id")
    ]

    deliveries = [
        {
            "query": query_labels[d.query_id],
            "external_id": d.ad.external_id,
            "status": d.status,
            "filter_reason": d.filter_reason,
            "send_attempts": d.send_attempts,
            "has_sent_at": d.sent_at is not None,
        }
        for d in AdDelivery.objects.select_related("ad").order_by("ad__external_id", "query_id")
    ]

    return {
        "ads": ads,
        "deliveries": deliveries,
        "discord_messages": sorted(sent_messages),
    }


def assert_matches_snapshot(name: str, state: dict) -> None:
    path = SNAPSHOT_DIR / f"{name}.json"
    serialised = json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

    if os.environ.get("UPDATE_SNAPSHOTS"):
        SNAPSHOT_DIR.mkdir(exist_ok=True)
        path.write_text(serialised, encoding="utf-8")
        pytest.skip(f"snapshot {name} regenerated")

    assert path.exists(), f"missing snapshot {path} — run with UPDATE_SNAPSHOTS=1"
    assert json.loads(serialised) == json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Pass 1 — a cold pipeline
# ---------------------------------------------------------------------------

@pytest.mark.vcr
@pytest.mark.django_db
def test_full_pipeline_first_pass(permissive_query, blocklist_query, sent_messages):
    labels = {permissive_query.pk: "permissive", blocklist_query.pk: "blocklist"}

    run_pipeline([permissive_query, blocklist_query], sent_messages)

    assert_matches_snapshot("pipeline_pass1", snapshot_state(labels, sent_messages))


@pytest.mark.vcr
@pytest.mark.django_db
def test_one_ad_row_per_listing_with_a_delivery_per_query(
    permissive_query, blocklist_query, sent_messages
):
    """The Ad/AdDelivery split: two queries watching one listing share the Ad."""
    run_pipeline([permissive_query, blocklist_query], sent_messages)

    assert Ad.objects.count() > 0
    assert AdDelivery.objects.count() == Ad.objects.count() * 2
    for ad in Ad.objects.all():
        assert ad.deliveries.count() == 2


@pytest.mark.vcr
@pytest.mark.django_db
def test_blocklist_query_rejects_only_the_blocked_ads(
    permissive_query, blocklist_query, sent_messages
):
    run_pipeline([permissive_query, blocklist_query], sent_messages)

    rejected = AdDelivery.objects.filter(query=blocklist_query, status=AdStatus.REJECTED)
    assert rejected.exists(), "blocklist matched nothing — has the recorded page changed?"
    for delivery in rejected.select_related("ad"):
        haystack = f"{delivery.ad.name} {delivery.ad.short_description}".lower()
        assert any(word in haystack for word in BLOCKLIST)
        assert delivery.filter_reason.startswith("blocklisted keyword:")

    # The same ads are APPROVED and SENT for the query that does not blocklist them.
    assert not AdDelivery.objects.filter(query=permissive_query, status=AdStatus.REJECTED).exists()
    assert AdDelivery.objects.filter(query=permissive_query, status=AdStatus.SENT).count() == Ad.objects.count()


@pytest.mark.vcr
@pytest.mark.django_db
def test_every_approved_delivery_produces_one_discord_message(
    permissive_query, blocklist_query, sent_messages
):
    run_pipeline([permissive_query, blocklist_query], sent_messages)

    sent = AdDelivery.objects.filter(status=AdStatus.SENT).count()
    assert sent > 0
    assert len(sent_messages) == sent
    for message in sent_messages:
        assert "https://" in message   # the ad link survived formatting


# ---------------------------------------------------------------------------
# Pass 2 — dedup. The single most refactor-sensitive behaviour in the codebase,
# and until now covered only at mock level.
# ---------------------------------------------------------------------------

@pytest.mark.vcr
@pytest.mark.django_db
def test_second_pass_creates_no_new_deliveries(
    permissive_query, blocklist_query, sent_messages
):
    labels = {permissive_query.pk: "permissive", blocklist_query.pk: "blocklist"}

    run_pipeline([permissive_query, blocklist_query], sent_messages)
    after_first = snapshot_state(labels, sent_messages)
    messages_after_first = len(sent_messages)

    run_pipeline([permissive_query, blocklist_query], sent_messages)
    after_second = snapshot_state(labels, sent_messages)

    assert after_second["ads"] == after_first["ads"]
    assert after_second["deliveries"] == after_first["deliveries"]
    assert len(sent_messages) == messages_after_first, "an ad was re-sent on the second pass"
    assert_matches_snapshot("pipeline_pass2", after_second)


@pytest.mark.vcr
@pytest.mark.django_db
def test_second_pass_stops_early_instead_of_walking_every_page(
    permissive_query, sent_messages
):
    """A caught-up query must stop at the first known ad, not re-walk the listing."""
    session = requests.Session()

    first = BazosQueryRunner(permissive_query, session)
    first.run()
    rows_seen_cold = first.rows_seen_counter

    second = BazosQueryRunner(permissive_query, session)
    new_products = second.run()

    assert new_products == 0
    assert second.rows_seen_counter < rows_seen_cold
