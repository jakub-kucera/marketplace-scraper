"""Tests for the delisting sweep — the only outcome data the project collects.

Two properties matter more than the rest and are tested hardest:

- a failed request must never be recorded as a removal (it would write false deaths into the
  one table meant to hold truth), and
- an ad past the watch horizon must be left with `removed_at` NULL — a censored observation,
  not a claim that it is still listed.
"""
from datetime import timedelta
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from marketplace.const import API_PAGE_SIZE, DELIST_BATCH_SIZE, DELIST_MAX_AGE_DAYS
from marketplace.delisting import apply_batch, due_for_check, recheck_interval_days
from marketplace.exceptions import MarketplaceBlockedError
from marketplace.models import Ad, AdDelivery, AdStatus, Marketplace, PriceChange


@pytest.fixture
def make_live_ad(query, make_ad):
    """A saved Bazos ad with controllable age and last-check time."""
    counter = iter(range(70000, 79999))

    def _factory(age_days=0, last_seen_days_ago=None, price_raw="1000 Kč", price=1000):
        ad = make_ad(query, next(counter))
        ad.price_raw, ad.price = price_raw, price
        ad.save()
        now = timezone.now()
        fields = {"created": now - timedelta(days=age_days)}
        if last_seen_days_ago is not None:
            fields["last_seen_at"] = now - timedelta(days=last_seen_days_ago)
        Ad.objects.filter(pk=ad.pk).update(**fields)
        ad.refresh_from_db()
        return ad

    return _factory


# ---------------------------------------------------------------------------
# The schedule
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("age,expected", [(0, 1), (2.9, 1), (3, 3), (13, 3), (14, 7), (59, 7)])
def test_recheck_interval_by_age(age, expected):
    assert recheck_interval_days(age) == expected


def test_watching_stops_past_the_horizon():
    assert recheck_interval_days(DELIST_MAX_AGE_DAYS) is None
    assert recheck_interval_days(DELIST_MAX_AGE_DAYS + 30) is None


def test_priority_ads_are_checked_sooner():
    fast, normal = recheck_interval_days(20, priority=True), recheck_interval_days(20)

    assert fast is not None and normal is not None
    assert fast < normal


# ---------------------------------------------------------------------------
# due_for_check
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_never_swept_ads_are_due(make_live_ad):
    ad = make_live_ad(age_days=1)

    assert ad in due_for_check()


@pytest.mark.django_db
def test_recently_swept_young_ad_is_not_due(make_live_ad):
    make_live_ad(age_days=1, last_seen_days_ago=0)

    assert due_for_check().count() == 0


@pytest.mark.django_db
def test_old_ad_swept_yesterday_is_not_due(make_live_ad):
    """A 30-day-old ad is on the weekly tier, so yesterday's check still counts."""
    make_live_ad(age_days=30, last_seen_days_ago=1)

    assert due_for_check().count() == 0


@pytest.mark.django_db
def test_old_ad_swept_long_ago_is_due(make_live_ad):
    ad = make_live_ad(age_days=30, last_seen_days_ago=10)

    assert ad in due_for_check()


@pytest.mark.django_db
def test_ads_past_the_horizon_are_never_due(make_live_ad):
    make_live_ad(age_days=DELIST_MAX_AGE_DAYS + 5)

    assert due_for_check().count() == 0


@pytest.mark.django_db
def test_already_removed_ads_are_not_rechecked(make_live_ad):
    ad = make_live_ad(age_days=1)
    Ad.objects.filter(pk=ad.pk).update(removed_at=timezone.now())

    assert due_for_check().count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("marketplace", [Marketplace.VINTED, Marketplace.SBAZAR])
def test_marketplaces_without_a_bulk_endpoint_are_skipped(make_live_ad, marketplace):
    """One request per ad would invert the economics that make this affordable."""
    ad = make_live_ad(age_days=1)
    Ad.objects.filter(pk=ad.pk).update(marketplace=marketplace)

    assert due_for_check().count() == 0


@pytest.mark.django_db
def test_a_sent_ad_is_checked_sooner_than_an_unnotified_one(make_live_ad, query, make_delivery):
    """Priority buys resolution where the outcome calibrates something — but note the
    un-notified ad is still watched, just less often. It is the control group."""
    plain = make_live_ad(age_days=20, last_seen_days_ago=4)
    notified = make_live_ad(age_days=20, last_seen_days_ago=4)
    delivery = make_delivery(notified, query)
    AdDelivery.objects.filter(pk=delivery.pk).update(status=AdStatus.SENT)

    due = list(due_for_check())

    assert notified in due
    assert plain not in due


# ---------------------------------------------------------------------------
# apply_batch
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_absent_ids_are_marked_removed(make_live_ad):
    gone = make_live_ad(age_days=2)

    result = apply_batch([gone], found={})

    gone.refresh_from_db()
    assert gone.removed_at is not None
    assert result.newly_removed == 1


@pytest.mark.django_db
def test_present_ids_get_a_fresh_last_seen(make_live_ad):
    alive = make_live_ad(age_days=2)

    apply_batch([alive], found={alive.external_id: {"id": alive.external_id}})

    alive.refresh_from_db()
    assert alive.last_seen_at is not None
    assert alive.removed_at is None


@pytest.mark.django_db
def test_a_price_change_is_recorded_and_refans_out(make_live_ad, query, make_delivery):
    """The bulk response carries price for free, so the sweep doubles as comprehensive
    price-change detection."""
    ad = make_live_ad(age_days=2, price_raw="10 000 Kč", price=10000)
    delivery = make_delivery(ad, query)

    result = apply_batch([ad], found={ad.external_id: {"id": ad.external_id, "price_formatted": "8 000 Kč"}})

    ad.refresh_from_db()
    delivery.refresh_from_db()
    assert (ad.price_raw, ad.price) == ("8 000 Kč", 8000)
    assert PriceChange.objects.filter(ad=ad).count() == 1
    assert delivery.status == AdStatus.PRICE_CHANGED
    assert result.price_changes == 1


@pytest.mark.django_db
def test_an_unchanged_price_writes_no_history(make_live_ad):
    ad = make_live_ad(age_days=2, price_raw="1000 Kč", price=1000)

    apply_batch([ad], found={ad.external_id: {"id": ad.external_id, "price_formatted": "1000 Kč"}})

    assert PriceChange.objects.filter(ad=ad).count() == 0


@pytest.mark.django_db
def test_removal_is_idempotent(make_live_ad):
    """A second sweep must not move `removed_at` — time-to-disappear is measured from it."""
    ad = make_live_ad(age_days=2)
    apply_batch([ad], found={})
    ad.refresh_from_db()
    first = ad.removed_at

    assert ad not in due_for_check()
    ad.refresh_from_db()
    assert ad.removed_at == first


# ---------------------------------------------------------------------------
# The command — batching, and the failure contract
# ---------------------------------------------------------------------------

def run_command(**kwargs):
    out = StringIO()
    call_command("check_delisted", stdout=out, **kwargs)
    return out.getvalue()


@pytest.mark.django_db
def test_dry_run_makes_no_request_and_writes_nothing(make_live_ad):
    ad = make_live_ad(age_days=1)

    with patch("marketplace.management.commands.check_delisted.BazosApiScraper") as scraper_cls:
        report = run_command(dry_run=True)

    scraper_cls.assert_not_called()
    ad.refresh_from_db()
    assert ad.last_seen_at is None
    assert "1 ads due" in report


@pytest.mark.django_db
def test_a_blocked_batch_is_skipped_not_recorded_as_removed(make_live_ad):
    """The property that matters most. Tor 403s about half of all attempts; treating that
    as evidence of removal would write thousands of false deaths in one bad hour."""
    ad = make_live_ad(age_days=1)
    scraper = MagicMock()
    scraper.fetch_by_ids.side_effect = MarketplaceBlockedError(exit_ip="1.2.3.4")
    changer = MagicMock()
    changer.rotate_circuit.return_value = False

    with patch("marketplace.management.commands.check_delisted.BazosApiScraper", return_value=scraper), \
         patch.object(type(_command()), "_ip_changer", return_value=changer):
        run_command()

    ad.refresh_from_db()
    assert ad.removed_at is None
    assert ad.last_seen_at is None


@pytest.mark.django_db
def test_a_failed_request_is_not_recorded_as_removal(make_live_ad):
    """The regression that shipped on 2026-09-17.

    A cold Tor circuit made `run_request` exhaust its retries. `fetch_by_ids` returned `{}`,
    the command read that as a successful response listing nothing, and `apply_batch` marked
    every ad in the batch removed. The block path was guarded and tested; this one — an
    ordinary network failure — was not.
    """
    ad = make_live_ad(age_days=1)
    scraper = MagicMock()
    scraper.fetch_by_ids.return_value = None   # no usable answer

    with patch("marketplace.management.commands.check_delisted.BazosApiScraper", return_value=scraper), \
         patch.object(type(_command()), "_ip_changer", return_value=MagicMock()):
        run_command()

    ad.refresh_from_db()
    assert ad.removed_at is None, "a failed request must never be recorded as a removal"
    assert ad.last_seen_at is None


@pytest.mark.django_db
def test_an_empty_but_successful_response_does_record_removal(make_live_ad):
    """The other half: `{}` from a real 200 genuinely means every id is gone."""
    ad = make_live_ad(age_days=1)
    scraper = MagicMock()
    scraper.fetch_by_ids.return_value = {}

    with patch("marketplace.management.commands.check_delisted.BazosApiScraper", return_value=scraper), \
         patch.object(type(_command()), "_ip_changer", return_value=MagicMock()):
        run_command()

    ad.refresh_from_db()
    assert ad.removed_at is not None


@pytest.mark.django_db
def test_a_successful_sweep_records_both_outcomes(make_live_ad):
    alive = make_live_ad(age_days=1)
    gone = make_live_ad(age_days=1)
    scraper = MagicMock()
    scraper.fetch_by_ids.return_value = {alive.external_id: {"id": alive.external_id}}

    with patch("marketplace.management.commands.check_delisted.BazosApiScraper", return_value=scraper), \
         patch.object(type(_command()), "_ip_changer", return_value=MagicMock()):
        run_command()

    alive.refresh_from_db()
    gone.refresh_from_db()
    assert alive.removed_at is None and alive.last_seen_at is not None
    assert gone.removed_at is not None


@pytest.mark.django_db
def test_batches_are_capped_at_the_api_limit(make_live_ad):
    """210 is the server's hard cap; a 211th id is silently dropped, which would read as a
    removal."""
    for _ in range(DELIST_BATCH_SIZE + 5):
        make_live_ad(age_days=1)
    scraper = MagicMock()
    scraper.fetch_by_ids.return_value = {}

    with patch("marketplace.management.commands.check_delisted.BazosApiScraper", return_value=scraper), \
         patch.object(type(_command()), "_ip_changer", return_value=MagicMock()), \
         patch("marketplace.management.commands.check_delisted.sleep"):
        run_command()

    sizes = [len(call.args[0]) for call in scraper.fetch_by_ids.call_args_list]
    assert max(sizes) <= DELIST_BATCH_SIZE
    assert sum(sizes) == DELIST_BATCH_SIZE + 5


def _command():
    from marketplace.management.commands.check_delisted import Command

    return Command()


# ---------------------------------------------------------------------------
# BazosApiScraper.fetch_by_ids — the transport contract
# ---------------------------------------------------------------------------

def _scraper():
    from marketplace.scraping.bazos.bazos_api_scraper import BazosApiScraper

    return BazosApiScraper(MagicMock())


def _response(status=200, payload=None):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = payload if payload is not None else []
    return response


def test_fetch_by_ids_keys_rows_by_id():
    scraper = _scraper()
    rows = [{"id": 11, "price_formatted": "1 Kč"}, {"id": 22}]

    with patch.object(scraper, "run_request", return_value=_response(payload=rows)):
        found = scraper.fetch_by_ids([11, 22, 33])

    assert set(found) == {11, 22}
    assert found[11]["price_formatted"] == "1 Kč"


def test_fetch_by_ids_makes_no_request_for_an_empty_batch():
    scraper = _scraper()

    with patch.object(scraper, "run_request") as run_request:
        assert scraper.fetch_by_ids([]) == {}

    run_request.assert_not_called()


@pytest.mark.parametrize("status", [403, 429])
def test_fetch_by_ids_raises_on_a_block_so_the_caller_can_rotate(status):
    scraper = _scraper()
    response = _response(status=status)
    response.text = "IP: 1.2.3.4"

    with patch.object(scraper, "run_request", return_value=response):
        with pytest.raises(MarketplaceBlockedError):
            scraper.fetch_by_ids([1])


@pytest.mark.parametrize("response", [None, _response(status=500), _response(payload={"not": "a list"})])
def test_fetch_by_ids_returns_none_when_it_has_no_answer(response):
    """`None` and `{}` mean opposite things here, and conflating them destroys data:
    `{}` is "a successful response listed none of these, they are all gone", while `None`
    is "no usable answer, record nothing"."""
    scraper = _scraper()

    with patch.object(scraper, "run_request", return_value=response):
        assert scraper.fetch_by_ids([1, 2]) is None


def test_fetch_by_ids_returns_empty_dict_for_a_genuinely_empty_result():
    """The distinction above, from the other side: a 200 listing no ids IS the removal
    signal and must stay distinguishable from a failure."""
    scraper = _scraper()

    with patch.object(scraper, "run_request", return_value=_response(payload=[])):
        assert scraper.fetch_by_ids([1, 2]) == {}


# ---------------------------------------------------------------------------
# AdOutcome — the ground truth that makes the proxy interpretable
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_an_ad_has_at_most_one_outcome(make_live_ad):
    from django.db import IntegrityError

    from marketplace.models import AdOutcome, OutcomeKind

    ad = make_live_ad()
    AdOutcome.objects.create(ad=ad, kind=OutcomeKind.BOUGHT, realised_price=900)

    with pytest.raises(IntegrityError):
        AdOutcome.objects.create(ad=ad, kind=OutcomeKind.REJECTED)


@pytest.mark.django_db
def test_outcome_is_reachable_from_the_ad(make_live_ad):
    from marketplace.models import AdOutcome, OutcomeKind

    ad = make_live_ad()
    AdOutcome.objects.create(ad=ad, kind=OutcomeKind.LOST)

    ad.refresh_from_db()
    assert ad.outcome.kind == OutcomeKind.LOST


@pytest.mark.django_db
def test_realised_price_is_optional(make_live_ad):
    """Null even for BOUGHT when the number was never agreed — an asking price copied in
    here would poison the one table meant to hold truth."""
    from marketplace.models import AdOutcome, OutcomeKind

    ad = make_live_ad()
    outcome = AdOutcome.objects.create(ad=ad, kind=OutcomeKind.BOUGHT)

    assert outcome.realised_price is None


@pytest.mark.django_db
def test_deleting_an_ad_takes_its_outcome(make_live_ad):
    from marketplace.models import AdOutcome, OutcomeKind

    ad = make_live_ad()
    AdOutcome.objects.create(ad=ad, kind=OutcomeKind.CONTACTED)
    AdDelivery.objects.filter(ad=ad).delete()
    ad.delete()

    assert AdOutcome.objects.count() == 0


def test_fetch_by_ids_asks_for_a_page_big_enough_to_hold_the_whole_batch():
    """The request must carry `limit`, because the server pages this endpoint at 30.

    Shipped without it, `ads.php` answered a 210-id batch with its default 30 rows and
    `apply_batch` read the 180 absent ids as removals - 19 008 rows, measured 56% false on a
    random sample of 200 re-checked against the live API (2026-09-19). Nothing in the
    response distinguishes "truncated" from "gone", so the only defence is asking for a page
    that cannot truncate.

    This asserts the outgoing params, not the parsed result: a stubbed response returns the
    same dict either way, so a test that only reads the return value passes on the bug.
    """
    scraper = _scraper()

    with patch.object(scraper, "run_request", return_value=_response(payload=[])) as run_request:
        scraper.fetch_by_ids(list(range(1000, 1210)))

    params = run_request.call_args.kwargs["params"]
    assert params["limit"] >= 210, f"batch of 210 asked for limit={params.get('limit')!r}"


def test_fetch_by_ids_refuses_a_batch_larger_than_one_page():
    """Truncation is prevented by construction, not by a constant happening to match.

    `DELIST_BATCH_SIZE == API_PAGE_SIZE` is what makes the caller safe today, and nothing
    pins the two together. A batch past one page must fail loudly rather than come back
    silently short and be written as removals.
    """
    scraper = _scraper()

    with patch.object(scraper, "run_request") as run_request:
        with pytest.raises(ValueError, match="page"):
            scraper.fetch_by_ids(list(range(API_PAGE_SIZE + 1)))

    run_request.assert_not_called()


# ---------------------------------------------------------------------------
# repair_false_removals - undoing what the mis-paginated sweep wrote
# ---------------------------------------------------------------------------

def _repair_command():
    from marketplace.management.commands.repair_false_removals import Command

    return Command()


@pytest.fixture
def removed_ad(make_live_ad):
    """An ad the sweep has already marked removed, two days ago."""
    def _factory():
        ad = make_live_ad()
        when = timezone.now() - timedelta(days=2)
        Ad.objects.filter(pk=ad.pk).update(removed_at=when, last_seen_at=when)
        ad.refresh_from_db()
        return ad
    return _factory


def _run_repair(command, found, **opts):
    options = {"since": None, "limit": None, "dry_run": False, **opts}
    with patch.object(command, "_fetch", return_value=found), \
            patch("marketplace.management.commands.repair_false_removals.build_ip_changer"):
        command.handle(**options)


@pytest.mark.django_db
def test_repair_clears_removed_at_only_for_ads_that_come_back(removed_ad):
    """The whole point: a still-listed ad is un-removed, a genuinely gone one is left alone.

    Its original `removed_at` is a better estimate of when it went than `now()` is, so a
    confirmed-gone ad must not be re-stamped.
    """
    alive, gone = removed_ad(), removed_ad()
    gone_at = gone.removed_at

    _run_repair(_repair_command(), {alive.external_id: {"id": alive.external_id}})

    alive.refresh_from_db()
    gone.refresh_from_db()
    assert alive.removed_at is None and alive.last_seen_at is not None
    assert gone.removed_at == gone_at


@pytest.mark.django_db
def test_repair_writes_nothing_on_a_failed_batch(removed_ad):
    """No usable answer is not evidence, exactly as in the sweep. A possibly-false removal
    survives a failed run rather than being cleared on no information."""
    ad = removed_ad()

    _run_repair(_repair_command(), None)

    ad.refresh_from_db()
    assert ad.removed_at is not None


@pytest.mark.django_db
def test_repair_dry_run_writes_nothing(removed_ad):
    ad = removed_ad()

    _run_repair(_repair_command(), {ad.external_id: {"id": ad.external_id}}, dry_run=True)

    ad.refresh_from_db()
    assert ad.removed_at is not None
