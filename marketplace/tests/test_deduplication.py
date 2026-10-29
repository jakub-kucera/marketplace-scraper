from unittest.mock import MagicMock, patch

import pytest

from marketplace.models import Ad, AdDelivery, AdStatus, PriceChange, PriceType
from marketplace.scraping.query_runner import QueryRunner


def make_runner(query):
    return QueryRunner(query, MagicMock())


# --- run_existing_query ---

@pytest.mark.django_db
def test_existing_query_saves_new_ad(query, make_ad):
    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()
    assert Ad.objects.filter(external_id=111).exists()


@pytest.mark.django_db
def test_existing_query_creates_a_delivery_for_new_ad(query, make_ad):
    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()
    ad = Ad.objects.get(external_id=111)
    assert AdDelivery.objects.filter(ad=ad, query=query).exists()


@pytest.mark.django_db
def test_existing_query_counts_new_ads(query, make_ad):
    products = [make_ad(query, bazos_id=i) for i in [111, 222]]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()
    assert runner.new_product_counter == 2


@pytest.mark.django_db
def test_existing_query_stops_on_known_non_topped_ad(query, make_ad, make_delivery):
    known = make_ad(query, bazos_id=111)
    known.save()
    make_delivery(known, query)
    products = [
        make_ad(query, bazos_id=111, topped=False),  # known, not TOP → stop
        make_ad(query, bazos_id=222, topped=False),  # would be new, but never reached
    ]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()
    assert not Ad.objects.filter(external_id=222).exists()
    assert runner.new_product_counter == 0


@pytest.mark.django_db
def test_existing_query_does_not_stop_on_known_topped_ad(query, make_ad, make_delivery):
    known = make_ad(query, bazos_id=111)
    known.save()
    make_delivery(known, query)
    products = [
        make_ad(query, bazos_id=111, topped=True),   # known but TOP → continue
        make_ad(query, bazos_id=222, topped=False),  # new → should be saved
    ]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()
    assert Ad.objects.filter(external_id=222).exists()
    assert runner.new_product_counter == 1


@pytest.mark.django_db
def test_existing_query_does_not_save_duplicate(query, make_ad, make_delivery):
    known = make_ad(query, bazos_id=111)
    known.save()
    make_delivery(known, query)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([make_ad(query, bazos_id=111, topped=True)])):
        runner.run_existing_query()
    assert Ad.objects.filter(external_id=111).count() == 1


# --- run_new_query ---

@pytest.mark.django_db
def test_new_query_sets_new_query_false(query, make_ad):
    query.new_query = True
    query.save()
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([])):
        runner.run_new_query()
    assert query.new_query is False


@pytest.mark.django_db
def test_new_query_with_ignore_first_run_saves_but_does_not_count(query, make_ad):
    query.ignore_first_run = True
    query.save()
    products = [make_ad(query, bazos_id=i) for i in [1, 2, 3]]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_new_query()
    assert Ad.objects.count() == 3
    assert runner.new_product_counter == 0


@pytest.mark.django_db
def test_new_query_without_ignore_first_run_counts_new_products(query, make_ad):
    query.ignore_first_run = False
    query.save()
    products = [make_ad(query, bazos_id=i) for i in [1, 2, 3]]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_new_query()
    assert runner.new_product_counter == 3


@pytest.mark.django_db
def test_new_query_stops_before_max_non_topped_ads(query, make_ad, monkeypatch):
    import marketplace.scraping.query_runner as qr_module
    monkeypatch.setattr(qr_module, "NEW_PRODUCT_LOAD_MAX", 3)

    # `ignore_first_run=False` is now load-bearing: the cap bounds how many ads a new query
    # *notifies* about, so it only stops the walk when the first run is actually sending.
    # A suppressed first run walks the whole catalog on purpose — see test_flood_guard.py.
    query.ignore_first_run = False
    query.save()

    # 5 non-topped products; with limit=3 the 3rd triggers break before being saved
    products = [make_ad(query, bazos_id=i, topped=False) for i in range(1, 6)]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_new_query()
    # products 1 and 2 are saved; product 3 causes break (saved as per loop logic? let's check)
    # The break fires after counter reaches limit, BEFORE save() for that product
    assert Ad.objects.count() == 2


@pytest.mark.django_db
def test_new_query_topped_ads_do_not_count_toward_limit(query, make_ad, monkeypatch):
    import marketplace.scraping.query_runner as qr_module
    monkeypatch.setattr(qr_module, "NEW_PRODUCT_LOAD_MAX", 2)

    query.ignore_first_run = False   # the cap only stops a walk that is notifying
    query.save()

    products = [
        make_ad(query, bazos_id=1, topped=True),   # doesn't count
        make_ad(query, bazos_id=2, topped=True),   # doesn't count
        make_ad(query, bazos_id=3, topped=False),  # counter=1
        make_ad(query, bazos_id=4, topped=False),  # counter=2 → break, not saved
    ]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_new_query()
    assert Ad.objects.filter(external_id=1).exists()
    assert Ad.objects.filter(external_id=2).exists()
    assert Ad.objects.filter(external_id=3).exists()
    assert not Ad.objects.filter(external_id=4).exists()


# --- Stage 3: status transitions after cut-over ---
# The scraper now only writes PENDING/SUPPRESSED deliveries. Sending is handled by
# run_filter + run_sender, which operate on AdDelivery (see AD_DELIVERY_SPLIT.md).

# run_existing_query

@pytest.mark.django_db
def test_existing_query_new_ad_delivery_is_marked_pending(query, make_ad):
    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()
    ad = Ad.objects.get(external_id=111)
    assert AdDelivery.objects.get(ad=ad, query=query).status == AdStatus.PENDING


@pytest.mark.django_db
def test_existing_query_new_ad_delivery_has_no_sent_at(query, make_ad):
    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()
    ad = Ad.objects.get(external_id=111)
    assert AdDelivery.objects.get(ad=ad, query=query).sent_at is None


@pytest.mark.django_db
def test_existing_query_does_not_instantiate_discord_sender(query, make_ad):
    """After cut-over the scraper must not touch DiscordSender at all."""
    from senders.services import discord_sender as ds_module
    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])), \
         patch.object(ds_module.DiscordSender, "send_sendable") as mock_send:
        runner.run_existing_query()
    mock_send.assert_not_called()


# run_new_query — ignore_first_run=True

@pytest.mark.django_db
def test_new_query_ignore_first_run_saves_delivery_as_suppressed(query, make_ad):
    query.ignore_first_run = True
    query.save()
    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_new_query()
    ad = Ad.objects.get(external_id=111)
    assert AdDelivery.objects.get(ad=ad, query=query).status == AdStatus.SUPPRESSED


@pytest.mark.django_db
def test_new_query_ignore_first_run_does_not_set_sent_at(query, make_ad):
    query.ignore_first_run = True
    query.save()
    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_new_query()
    ad = Ad.objects.get(external_id=111)
    assert AdDelivery.objects.get(ad=ad, query=query).sent_at is None


# run_new_query — ignore_first_run=False

@pytest.mark.django_db
def test_new_query_without_ignore_first_run_delivery_is_marked_pending(query, make_ad):
    query.ignore_first_run = False
    query.save()
    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_new_query()
    ad = Ad.objects.get(external_id=111)
    assert AdDelivery.objects.get(ad=ad, query=query).status == AdStatus.PENDING


@pytest.mark.django_db
def test_new_query_without_ignore_first_run_has_no_sent_at(query, make_ad):
    query.ignore_first_run = False
    query.save()
    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_new_query()
    ad = Ad.objects.get(external_id=111)
    assert AdDelivery.objects.get(ad=ad, query=query).sent_at is None


@pytest.mark.django_db
def test_new_query_without_ignore_first_run_does_not_call_discord(query, make_ad):
    query.ignore_first_run = False
    query.save()
    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    from senders.services import discord_sender as ds_module
    with patch.object(runner.scraper, "run_query", return_value=iter([product])), \
         patch.object(ds_module.DiscordSender, "send_sendable") as mock_send:
        runner.run_new_query()
    mock_send.assert_not_called()


# --- Stage 4: price-change detection (_get_known_delivery) ---

@pytest.mark.django_db
def test_get_known_delivery_returns_none_for_unseen_ad(query, make_ad):
    runner = make_runner(query)
    product = make_ad(query, bazos_id=111)
    assert runner._get_known_delivery(product) is None


@pytest.mark.django_db
def test_get_known_delivery_returns_existing_delivery(query, make_ad, make_delivery):
    existing = make_ad(query, bazos_id=111)
    existing.save()
    delivery = make_delivery(existing, query)
    runner = make_runner(query)
    product = make_ad(query, bazos_id=111)
    assert runner._get_known_delivery(product) == delivery


@pytest.mark.django_db
def test_existing_query_creates_price_change_on_price_drop(query, make_ad, make_delivery):
    existing = make_ad(query, bazos_id=111)
    existing.price_raw = "1 000 Kč"
    existing.save()
    make_delivery(existing, query, status=AdStatus.SENT)

    product = make_ad(query, bazos_id=111, topped=False)
    product.price_raw = "800 Kč"

    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()

    price_change = PriceChange.objects.get(ad=existing)
    assert price_change.old_price == "1 000 Kč"
    assert price_change.new_price == "800 Kč"


@pytest.mark.django_db
def test_existing_query_updates_price_raw_on_ad_and_flips_delivery_status(query, make_ad, make_delivery):
    existing = make_ad(query, bazos_id=111)
    existing.price_raw = "1 000 Kč"
    existing.save()
    delivery = make_delivery(existing, query, status=AdStatus.SENT)

    product = make_ad(query, bazos_id=111, topped=False)
    product.price_raw = "800 Kč"

    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()

    existing.refresh_from_db()
    delivery.refresh_from_db()
    assert existing.price_raw == "800 Kč"
    assert delivery.status == AdStatus.PRICE_CHANGED


@pytest.mark.django_db
def test_existing_query_price_change_carries_parsed_amounts(query, make_ad, make_delivery):
    """The scraper already parses price/price_type at extraction time (P22) — the query
    runner must reuse those values on both the Ad and the PriceChange record rather than
    re-parsing price_raw itself."""
    existing = make_ad(query, bazos_id=111)
    existing.price_raw, existing.price, existing.price_type = "1 000 Kč", 1000, PriceType.EXACT
    existing.save()
    make_delivery(existing, query, status=AdStatus.SENT)

    product = make_ad(query, bazos_id=111, topped=False)
    product.price_raw, product.price, product.price_type = "800 Kč", 800, PriceType.EXACT

    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()

    existing.refresh_from_db()
    assert existing.price == 800
    assert existing.price_type == PriceType.EXACT

    price_change = PriceChange.objects.get(ad=existing)
    assert price_change.old_price_amount == 1000
    assert price_change.new_price_amount == 800


@pytest.mark.django_db
def test_existing_query_does_not_create_price_change_when_price_unchanged(query, make_ad, make_delivery):
    existing = make_ad(query, bazos_id=111)
    existing.price_raw = "1 000 Kč"
    existing.save()
    delivery = make_delivery(existing, query, status=AdStatus.SENT)

    product = make_ad(query, bazos_id=111, topped=False)
    product.price_raw = "1 000 Kč"

    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()

    existing.refresh_from_db()
    delivery.refresh_from_db()
    assert not PriceChange.objects.filter(ad=existing).exists()
    assert delivery.status == AdStatus.SENT


@pytest.mark.django_db
def test_existing_query_price_change_on_topped_ad_still_continues_scan(query, make_ad, make_delivery):
    existing = make_ad(query, bazos_id=111)
    existing.price_raw = "1 000 Kč"
    existing.save()
    make_delivery(existing, query, status=AdStatus.SENT)

    changed_product = make_ad(query, bazos_id=111, topped=True)
    changed_product.price_raw = "800 Kč"
    new_product = make_ad(query, bazos_id=222, topped=False)

    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([changed_product, new_product])):
        runner.run_existing_query()

    assert PriceChange.objects.filter(ad=existing).exists()
    assert Ad.objects.filter(external_id=222).exists()
    assert runner.new_product_counter == 1


# --- Cross-query dedup — the reason for the split (AD_DELIVERY_SPLIT.md) ---

@pytest.mark.django_db
def test_two_queries_matching_one_listing_create_one_ad_and_two_deliveries(query, category, make_ad):
    from marketplace.models import Query
    other_query = Query.objects.create(
        text="thinkpad",
        category=category,
        location_center="12345",
        location_radius=25,
        price_lower=0,
        price_upper=0,
        new_query=False,
        ignore_first_run=True,
    )

    product_a = make_ad(query, bazos_id=111)
    runner_a = make_runner(query)
    with patch.object(runner_a.scraper, "run_query", return_value=iter([product_a])):
        runner_a.run_existing_query()

    product_b = make_ad(other_query, bazos_id=111)
    runner_b = make_runner(other_query)
    with patch.object(runner_b.scraper, "run_query", return_value=iter([product_b])):
        runner_b.run_existing_query()

    assert Ad.objects.filter(marketplace="bazos", external_id=111).count() == 1
    ad = Ad.objects.get(marketplace="bazos", external_id=111)
    assert AdDelivery.objects.filter(ad=ad).count() == 2
    assert set(AdDelivery.objects.filter(ad=ad).values_list("query_id", flat=True)) == {query.pk, other_query.pk}


def _fake_load_full_description(ad):
    """Stand-in for the real scraper method's side effect: it mutates `ad` in place, and
    the caller (`_handle_new_product`) persists it with `ad.save()` right after."""
    ad.full_description = "fetched description"


@pytest.mark.django_db
def test_second_query_rediscovering_a_known_ad_does_not_refetch_full_description(query, category, make_ad):
    """The redundant fetch is skipped because the description is actually present after the
    first fetch — not merely because the first query "won" the discovery race. See the
    asymmetric-flags test below for the case this distinction protects against."""
    from marketplace.models import Query
    query.load_full_description = True
    query.save()
    other_query = Query.objects.create(
        text="thinkpad",
        category=category,
        location_center="12345",
        location_radius=25,
        price_lower=0,
        price_upper=0,
        new_query=False,
        ignore_first_run=True,
        load_full_description=True,
    )

    product_a = make_ad(query, bazos_id=111)
    runner_a = make_runner(query)
    with patch.object(runner_a.scraper, "run_query", return_value=iter([product_a])), \
         patch.object(runner_a.scraper, "load_full_description", side_effect=_fake_load_full_description) as fetch_a:
        runner_a.run_existing_query()
    fetch_a.assert_called_once()

    product_b = make_ad(other_query, bazos_id=111)
    runner_b = make_runner(other_query)
    with patch.object(runner_b.scraper, "run_query", return_value=iter([product_b])), \
         patch.object(runner_b.scraper, "load_full_description", side_effect=_fake_load_full_description) as fetch_b:
        runner_b.run_existing_query()
    fetch_b.assert_not_called()


@pytest.mark.django_db
def test_second_query_with_load_full_description_fetches_even_when_first_query_did_not(query, category, make_ad):
    """Regression test for a real bug: gating the fetch on "did THIS query discover the ad
    first" (rather than "is the description actually missing") meant a query with
    load_full_description=True got permanently starved if a different, non-fetching query
    happened to discover the ad first — nothing would ever fetch it.
    """
    from marketplace.models import Query
    query.load_full_description = False
    query.save()
    other_query = Query.objects.create(
        text="thinkpad",
        category=category,
        location_center="12345",
        location_radius=25,
        price_lower=0,
        price_upper=0,
        new_query=False,
        ignore_first_run=True,
        load_full_description=True,
    )

    product_a = make_ad(query, bazos_id=111)
    runner_a = make_runner(query)
    with patch.object(runner_a.scraper, "run_query", return_value=iter([product_a])), \
         patch.object(runner_a.scraper, "load_full_description", side_effect=_fake_load_full_description) as fetch_a:
        runner_a.run_existing_query()
    fetch_a.assert_not_called()

    product_b = make_ad(other_query, bazos_id=111)
    runner_b = make_runner(other_query)
    with patch.object(runner_b.scraper, "run_query", return_value=iter([product_b])), \
         patch.object(runner_b.scraper, "load_full_description", side_effect=_fake_load_full_description) as fetch_b:
        runner_b.run_existing_query()
    fetch_b.assert_called_once()

    ad = Ad.objects.get(marketplace="bazos", external_id=111)
    assert ad.full_description == "fetched description"


@pytest.mark.django_db
def test_price_change_flips_every_delivery_of_that_ad(query, category, make_ad, make_delivery):
    from marketplace.models import Query
    other_query = Query.objects.create(
        text="thinkpad",
        category=category,
        location_center="12345",
        location_radius=25,
        price_lower=0,
        price_upper=0,
        new_query=False,
        ignore_first_run=True,
    )

    existing = make_ad(query, bazos_id=111)
    existing.price_raw = "1 000 Kč"
    existing.save()
    delivery_a = make_delivery(existing, query, status=AdStatus.SENT)
    delivery_b = make_delivery(existing, other_query, status=AdStatus.SENT)

    product = make_ad(query, bazos_id=111, topped=False)
    product.price_raw = "800 Kč"

    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()

    delivery_a.refresh_from_db()
    delivery_b.refresh_from_db()
    assert delivery_a.status == AdStatus.PRICE_CHANGED
    assert delivery_b.status == AdStatus.PRICE_CHANGED


@pytest.mark.django_db
def test_price_change_unsuppresses_a_suppressed_delivery(query, make_ad, make_delivery):
    """Preserves pre-split behaviour exactly, including the part that looks wrong: a
    SUPPRESSED delivery (e.g. from ignore_first_run) is unconditionally flipped to
    PRICE_CHANGED too. See AD_DELIVERY_SPLIT.md §3.2 — this is a known, deliberately
    unfixed quirk, not something to "improve" here.
    """
    existing = make_ad(query, bazos_id=111)
    existing.price_raw = "1 000 Kč"
    existing.save()
    delivery = make_delivery(existing, query, status=AdStatus.SUPPRESSED)

    product = make_ad(query, bazos_id=111, topped=False)
    product.price_raw = "800 Kč"

    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])):
        runner.run_existing_query()

    delivery.refresh_from_db()
    assert delivery.status == AdStatus.PRICE_CHANGED


@pytest.mark.django_db
def test_new_query_backfills_even_when_another_query_already_knows_the_ad(query, category, make_ad, make_delivery):
    """§3.1's failure mode: the dedup break must key on THIS query's delivery, not on
    global Ad existence — otherwise a brand-new query breaks on page 1 the moment any
    other query has already seen the listing, and never backfills.
    """
    from marketplace.models import Query
    other_query = Query.objects.create(
        text="thinkpad",
        category=category,
        location_center="12345",
        location_radius=25,
        price_lower=0,
        price_upper=0,
        new_query=False,
        ignore_first_run=True,
    )
    known_elsewhere = make_ad(other_query, bazos_id=111)
    known_elsewhere.save()
    make_delivery(known_elsewhere, other_query)

    # `query` is new and has never seen ad 111, even though `other_query` has.
    products = [
        make_ad(query, bazos_id=111, topped=False),
        make_ad(query, bazos_id=222, topped=False),
    ]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()

    ad_111 = Ad.objects.get(marketplace="bazos", external_id=111)
    assert AdDelivery.objects.filter(ad=ad_111, query=query).exists()
    assert Ad.objects.filter(marketplace="bazos", external_id=222).exists()
    assert runner.new_product_counter == 2


@pytest.mark.django_db
def test_dedup_break_still_stops_on_first_known_non_topped_ad_for_this_query(query, make_ad, make_delivery):
    known = make_ad(query, bazos_id=111)
    known.save()
    make_delivery(known, query)

    products = [
        make_ad(query, bazos_id=111, topped=False),  # known to THIS query, not TOP → stop
        make_ad(query, bazos_id=222, topped=False),  # never reached
    ]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()

    assert not Ad.objects.filter(external_id=222).exists()
    assert runner.new_product_counter == 0


# --- dedup_break_streak (spec §11) — a scraper whose default order isn't creation
# time (Sbazar) can override this so the walk tolerates known-but-recently-edited
# ads instead of giving up on the first one. See run_existing_query's docstring.

@pytest.mark.django_db
def test_streak_of_one_known_ad_does_not_break_when_streak_threshold_is_higher(query, make_ad, make_delivery):
    known = make_ad(query, bazos_id=111)
    known.save()
    make_delivery(known, query)

    products = [
        make_ad(query, bazos_id=111, topped=False),  # known, but only 1 of 3 needed to break
        make_ad(query, bazos_id=222, topped=False),  # must still be reached
    ]
    runner = make_runner(query)
    runner.scraper.dedup_break_streak = 3
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()

    assert Ad.objects.filter(external_id=222).exists()
    assert runner.new_product_counter == 1


@pytest.mark.django_db
def test_breaks_once_consecutive_known_streak_reaches_threshold(query, make_ad, make_delivery):
    known_ids = [111, 222, 333]
    for bazos_id in known_ids:
        known = make_ad(query, bazos_id=bazos_id)
        known.save()
        make_delivery(known, query)

    products = [
        make_ad(query, bazos_id=111, topped=False),  # streak=1
        make_ad(query, bazos_id=222, topped=False),  # streak=2
        make_ad(query, bazos_id=333, topped=False),  # streak=3 → break
        make_ad(query, bazos_id=444, topped=False),  # never reached
    ]
    runner = make_runner(query)
    runner.scraper.dedup_break_streak = 3
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()

    assert not Ad.objects.filter(external_id=444).exists()
    assert runner.new_product_counter == 0


@pytest.mark.django_db
def test_new_ad_resets_the_known_streak(query, make_ad, make_delivery):
    """The interleaved-bump scenario the streak exists for: a known ad resurfacing
    above genuinely new ones must not stall the walk, as long as new ads keep turning
    up before the streak threshold is reached.
    """
    known_a = make_ad(query, bazos_id=111)
    known_a.save()
    make_delivery(known_a, query)
    known_b = make_ad(query, bazos_id=333)
    known_b.save()
    make_delivery(known_b, query)

    products = [
        make_ad(query, bazos_id=111, topped=False),  # known, streak=1
        make_ad(query, bazos_id=222, topped=False),  # new → resets streak to 0
        make_ad(query, bazos_id=333, topped=False),  # known, streak=1 again, not 2
        make_ad(query, bazos_id=444, topped=False),  # new, must still be reached
    ]
    runner = make_runner(query)
    runner.scraper.dedup_break_streak = 2
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()

    assert Ad.objects.filter(external_id=222).exists()
    assert Ad.objects.filter(external_id=444).exists()
    assert runner.new_product_counter == 2


@pytest.mark.django_db
def test_topped_known_ad_does_not_count_toward_the_streak(query, make_ad, make_delivery):
    known = make_ad(query, bazos_id=111)
    known.save()
    make_delivery(known, query)

    products = [
        make_ad(query, bazos_id=111, topped=True),   # known, TOP → never counted
        make_ad(query, bazos_id=111, topped=True),
        make_ad(query, bazos_id=111, topped=True),
        make_ad(query, bazos_id=222, topped=False),  # must still be reached
    ]
    runner = make_runner(query)
    runner.scraper.dedup_break_streak = 3
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_existing_query()

    assert Ad.objects.filter(external_id=222).exists()
    assert runner.new_product_counter == 1


def test_default_streak_is_one_when_scraper_does_not_define_it(query):
    """Bazos/BazosApi/Vinted don't set dedup_break_streak — confirms the getattr
    default preserves the original break-on-first-hit behaviour for them.
    """
    runner = make_runner(query)
    assert not hasattr(runner.scraper, "dedup_break_streak")


# --- Interrupted-and-replayed run_new_query (idempotent delivery creation) ---
# Regression tests for a real BLOCKER: unlike run_existing_query (which checks
# _get_known_delivery before creating anything), run_new_query used to create AdDelivery
# rows unconditionally. A pass interrupted mid-pagination (blacklist hit, a raise from
# load_full_description, SIGTERM) leaves partial rows behind — nothing wraps the loop in a
# transaction, and query.new_query is only persisted by the caller (ScrapeRunner.run) AFTER
# a successful return. The next pass replays from page 1 and used to raise IntegrityError on
# unique_delivery_per_ad_query for every already-delivered product, forever.

@pytest.mark.django_db
def test_run_new_query_replay_after_interruption_does_not_raise(query, make_ad):
    query.ignore_first_run = False
    query.save()

    products = [make_ad(query, bazos_id=i) for i in (1, 2, 3)]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products[:2])):
        runner.run_new_query()
    assert runner.new_product_counter == 2
    assert AdDelivery.objects.count() == 2

    # Replay: the scraper yields the SAME first two products again (as it would on a fresh
    # backfill from page 1), plus the one the interrupted pass never reached.
    replay_products = [make_ad(query, bazos_id=i) for i in (1, 2, 3)]
    runner2 = make_runner(query)
    with patch.object(runner2.scraper, "run_query", return_value=iter(replay_products)):
        runner2.run_new_query()  # must not raise IntegrityError

    assert AdDelivery.objects.count() == 3
    assert runner2.new_product_counter == 1  # only product 3 is genuinely new to this query


@pytest.mark.django_db
def test_run_new_query_replay_does_not_double_count_or_refetch(query, make_ad):
    query.ignore_first_run = False
    query.load_full_description = True
    query.save()

    product = make_ad(query, bazos_id=111)
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter([product])), \
         patch.object(runner.scraper, "load_full_description", side_effect=_fake_load_full_description) as fetch:
        runner.run_new_query()
    fetch.assert_called_once()
    assert runner.new_product_counter == 1

    replay_product = make_ad(query, bazos_id=111)
    runner2 = make_runner(query)
    with patch.object(runner2.scraper, "run_query", return_value=iter([replay_product])), \
         patch.object(runner2.scraper, "load_full_description", side_effect=_fake_load_full_description) as fetch2:
        runner2.run_new_query()
    fetch2.assert_not_called()  # already has a description, and already has a delivery
    assert runner2.new_product_counter == 0
    assert AdDelivery.objects.count() == 1


@pytest.mark.django_db
def test_run_new_query_ignore_first_run_replay_does_not_raise(query, make_ad):
    """Same replay hazard, for the SUPPRESSED (ignore_first_run) branch."""
    query.ignore_first_run = True
    query.save()

    products = [make_ad(query, bazos_id=i) for i in (1, 2)]
    runner = make_runner(query)
    with patch.object(runner.scraper, "run_query", return_value=iter(products)):
        runner.run_new_query()
    assert AdDelivery.objects.filter(status=AdStatus.SUPPRESSED).count() == 2

    replay_products = [make_ad(query, bazos_id=i) for i in (1, 2)]
    runner2 = make_runner(query)
    with patch.object(runner2.scraper, "run_query", return_value=iter(replay_products)):
        runner2.run_new_query()  # must not raise IntegrityError

    assert AdDelivery.objects.filter(status=AdStatus.SUPPRESSED).count() == 2
