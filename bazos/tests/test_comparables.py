"""Tests for bazos/comparables.py, the notification line, and `manage.py appraise`.

The bucket an ad belongs to is read off `AdPriceScore.features`, so these build scores
directly rather than running a model — the model's job is covered in test_pricing.py, and
coupling these to a trained artifact would make them fail for the wrong reason.
"""
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from bazos.comparables import find_comparables
from bazos.management.commands.appraise import parse_target
from bazos.models import (
    Ad,
    AdDelivery,
    AdPriceScore,
    AdStatus,
    PostalCode,
    PriceChange,
    PriceType,
)
from bazos.pricing.estimators.macbook import MacbookPriceModel

M4_MAX_36_1TB = {"chip_key": "apple4_max", "ram_gb": 36, "ssd_gb": 1000, "screen": 14.0}


@pytest.fixture
def praha_brno(db):
    """Real zip.php coordinates, so distance output is a real number rather than a stub."""
    PostalCode.objects.create(code="11000", city="Praha", latitude=50.087334, longitude=14.421111)
    PostalCode.objects.create(code="60200", city="Brno", latitude=49.195060, longitude=16.606837)


@pytest.fixture
def scored(query, make_ad):
    """`scored(external_id, price, **feature_overrides)` -> a saved Ad with a score."""
    counter = iter(range(9000, 9999))

    def _factory(price, features=None, *, name=None, age_days=0, declined=False):
        ad = make_ad(query, next(counter))
        ad.price = price
        ad.price_raw = f"{price} Kč"
        # EXACT because that is the only price_type a model ever scores, and
        # `find_comparables` filters on it — a placeholder price is not a comparable.
        ad.price_type = PriceType.EXACT
        # A name the MacBook model's `applies_to` actually claims; the default from
        # `make_ad` is "Ad <id>", which no model recognises.
        ad.name = name or "MacBook Pro 14 M4 Max 36GB 1TB"
        ad.save()
        if age_days:
            Ad.objects.filter(pk=ad.pk).update(created=timezone.now() - timedelta(days=age_days))
            ad.refresh_from_db()
        AdPriceScore.objects.create(
            ad=ad, model_name="macbook", model_version="t1",
            predicted=None if declined else price + 5000,
            residual_log=None if declined else -0.1,
            discount_pct=None if declined else 8.0,
            z_score=None if declined else -1.2,
            features=None if declined else {**M4_MAX_36_1TB, **(features or {})},
            declined_reason="incomplete specs" if declined else None,
        )
        return ad

    return _factory


# ---------------------------------------------------------------------------
# find_comparables
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_groups_ads_sharing_a_spec_bucket(scored):
    subject = scored(61000)
    scored(65000)
    scored(45000, {"chip_key": "apple3_max"})   # previous generation — different bucket

    found = find_comparables(subject)

    assert found.count == 2
    assert found.prices == [61000, 65000]
    assert found.label == 'M4 Max 36GB/1TB 14"'


@pytest.mark.django_db
def test_marks_and_ranks_the_subject(scored):
    subject = scored(61000)
    scored(65000)

    found = find_comparables(subject)

    assert found.subject_rank == 1
    assert [row.is_subject for row in found.rows] == [True, False]


@pytest.mark.django_db
@pytest.mark.parametrize("differing", [
    {"ram_gb": 48}, {"ssd_gb": 2000}, {"screen": 16.0}, {"chip_key": "apple4_pro"},
])
def test_any_differing_spec_is_a_different_bucket(scored, differing):
    subject = scored(61000)
    scored(65000, differing)

    assert find_comparables(subject).count == 1


@pytest.mark.django_db
def test_ignores_listings_older_than_the_window(scored):
    subject = scored(61000)
    scored(30000, age_days=200)

    found = find_comparables(subject)

    assert found.count == 1
    assert 30000 not in found.prices


@pytest.mark.django_db
def test_no_comparables_without_a_score(query, make_ad):
    """An unscored ad has no spec vocabulary, so there is nothing to compare it on."""
    ad = make_ad(query, 1)
    ad.price = 61000
    ad.save()

    assert find_comparables(ad) is None


@pytest.mark.django_db
def test_no_comparables_for_a_declined_score(scored):
    """Declined means the model had no opinion — including about which bucket this is."""
    assert find_comparables(scored(61000, declined=True)) is None


@pytest.mark.django_db
def test_incomplete_bucket_declines_rather_than_matching_broadly(scored):
    """A null in the bucket would match every ad missing that same spec, which answers a
    different question from "the same machine"."""
    subject = scored(61000, {"ssd_gb": None})

    assert find_comparables(subject) is None


@pytest.mark.django_db
def test_median_and_span(scored):
    subject = scored(50000)
    for price in (60000, 70000, 80000):
        scored(price)

    found = find_comparables(subject)

    assert (found.cheapest, found.dearest) == (50000, 80000)
    assert found.median == 65000   # even count -> mean of the middle pair


# ---------------------------------------------------------------------------
# The notification line
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_summary_line_names_the_bucket_and_the_span(scored):
    subject = scored(61000)
    scored(65000)

    assert subject.comparables_summary == 'Similar (M4 Max 36GB/1TB 14"): 2 listed, 61k–65k — this is cheapest'


@pytest.mark.django_db
def test_summary_ranks_a_dearer_subject(scored):
    scored(55000)
    subject = scored(61000)

    assert subject.comparables_summary.endswith("— this is #2")


@pytest.mark.django_db
def test_no_line_when_the_subject_is_the_only_listing(scored):
    """"1 listed, 61k" tells you nothing you did not already have."""
    assert scored(61000).comparables_summary == ""


@pytest.mark.django_db
def test_message_appends_the_line_after_the_score(scored):
    subject = scored(61000)
    scored(65000)

    lines = subject.message.splitlines()

    assert lines[-2].startswith("Model: ")
    assert lines[-1].startswith("Similar (")


@pytest.mark.django_db
def test_unscored_ad_message_is_unchanged(query, make_ad):
    ad = make_ad(query, 1)
    ad.save()

    assert ad.comparables_summary == ""
    assert ad.message.endswith(ad.seller_ad_counts().summary)


@pytest.mark.django_db
def test_unscored_message_costs_no_comparables_query(query, make_ad, django_assert_num_queries):
    """An ad no model claims pays **nothing** for the score line, not even the lookup.

    `current_price_score` resolves the claiming model first, which is regex over two strings
    with no DB, so an ad that is neither a MacBook nor an iPhone skips the query entirely.
    That is most of `run_sender`'s batch, and it is a consequence of keying the read on
    `model_name` (docs/backlog/PRICE_MODEL_DEFECTS.md §9) rather than a separate
    optimisation. A *claimed* ad still pays exactly one, pinned below.

    These fixtures attach no publisher, so `seller_ad_counts` short-circuits to zero
    queries — which is the point: it isolates the cost this feature adds. The full
    identity-walk cost is pinned separately in test_seller_ad_counts.py.
    """
    ad = make_ad(query, 1)
    ad.save()

    with django_assert_num_queries(0):
        ad.message


@pytest.mark.django_db
def test_a_claimed_but_unscored_ad_still_pays_one_lookup(query, make_ad, django_assert_num_queries):
    """The other half of the above: skipping the query must depend on the claim, not on luck."""
    ad = make_ad(query, 2)
    ad.name = "MacBook Pro 14 2023 M3 Max 36GB 1TB"
    ad.save()

    with django_assert_num_queries(1):   # the score lookup, which finds nothing
        ad.message


@pytest.mark.django_db
def test_scored_message_reuses_one_score_lookup(scored, django_assert_num_queries):
    """Both lines need the score; it must be read once, not twice."""
    subject = scored(61000)
    scored(65000)

    with django_assert_num_queries(2):   # one score lookup + one comparables query
        subject.message


# ---------------------------------------------------------------------------
# Engine edges the happy path does not reach
# ---------------------------------------------------------------------------

class _StubModel:
    """A registered model with no opinion about comparability."""
    name = "stub"

    def applies_to(self, ad):
        return True


class _KeyedStub(_StubModel):
    """Declares comparable_keys but no describe_features, so the label falls back."""
    comparable_keys = ("chip_key",)


@pytest.mark.django_db
def test_median_of_an_odd_number_of_listings(scored):
    subject = scored(50000)
    scored(60000)
    scored(90000)

    assert find_comparables(subject).median == 60000


@pytest.mark.django_db
def test_subject_outside_the_window_is_ranked_as_absent(scored):
    """The subject is matched by the same filters as everyone else, so an ad too old to be
    its own comparable still gets a bucket — but no rank, and no "this is" suffix."""
    subject = scored(61000, age_days=200)
    scored(65000)
    scored(70000)

    found = find_comparables(subject)

    assert found.subject_rank is None
    assert found.summary().endswith("65k–70k")


@pytest.mark.django_db
def test_stale_ad_with_no_current_comparables_yields_nothing(scored):
    """An ad old enough to fall outside its own window, with nothing else in the bucket,
    has no comparables at all — not an empty set."""
    assert find_comparables(scored(61000, age_days=200)) is None


@pytest.mark.django_db
def test_single_price_renders_one_value_not_a_range(scored):
    subject = scored(61000, age_days=200)
    scored(65000)
    scored(65000)

    summary = find_comparables(subject).summary()

    assert "65k–65k" not in summary
    assert "2 listed, 65k" in summary


@pytest.mark.django_db
def test_model_without_comparable_keys_yields_nothing(scored, monkeypatch):
    """`comparable_keys` is optional — a model that predicts prices need not also have an
    opinion on what makes two listings the same."""
    monkeypatch.setattr("bazos.pricing.registry.MODEL_REGISTRY", {"macbook": _StubModel()})

    assert find_comparables(scored(61000)) is None


@pytest.mark.django_db
def test_score_from_an_unregistered_model_yields_nothing(scored, monkeypatch):
    """A score row outlives the model that wrote it — e.g. one deleted from the registry.
    There is then no vocabulary left to bucket on."""
    monkeypatch.setattr("bazos.pricing.registry.MODEL_REGISTRY", {})

    assert find_comparables(scored(61000)) is None


@pytest.mark.django_db
def test_label_falls_back_when_the_model_cannot_describe_itself(scored, monkeypatch):
    monkeypatch.setattr("bazos.pricing.registry.MODEL_REGISTRY", {"macbook": _KeyedStub()})
    subject = scored(61000)
    scored(65000)

    assert find_comparables(subject).label == "apple4_max"


@pytest.mark.django_db
def test_non_exact_prices_are_not_comparables(scored):
    """A "Dohodou" listing carries no number to compare against."""
    subject = scored(61000)
    other = scored(65000)
    Ad.objects.filter(pk=other.pk).update(price_type=PriceType.NEGOTIABLE)

    assert find_comparables(subject).count == 1


@pytest.mark.django_db
def test_buckets_do_not_cross_models(scored):
    """Two models can claim overlapping ads; their feature vocabularies are their own."""
    subject = scored(61000)
    other = scored(65000)
    AdPriceScore.objects.filter(ad=other).update(model_name="other_model")

    assert find_comparables(subject).count == 1


@pytest.mark.django_db
def test_row_count_is_capped(scored, monkeypatch):
    monkeypatch.setattr("bazos.comparables.COMPARABLE_MAX_ROWS", 3)
    subject = scored(50000)
    for price in (60000, 70000, 80000, 90000):
        scored(price)

    assert find_comparables(subject).count == 3


# ---------------------------------------------------------------------------
# describe_features
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bucket,expected", [
    (M4_MAX_36_1TB, 'M4 Max 36GB/1TB 14"'),
    ({"chip_key": "apple3_pro", "ram_gb": 18, "ssd_gb": 512, "screen": 16.0}, 'M3 Pro 18GB/512GB 16"'),
    ({"chip_key": "apple2_base", "ram_gb": 8, "ssd_gb": 256, "screen": 13.0}, 'M2 8GB/256GB 13"'),
])
def test_describe_features(bucket, expected):
    assert MacbookPriceModel.describe_features(bucket) == expected


# ---------------------------------------------------------------------------
# manage.py appraise
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("https://pc.bazos.cz/inzerat/223724249/macbook-14-m4-max.php", 223724249),
    ("pc.bazos.cz/inzerat/223724249/x.php", 223724249),
    ("223724249", 223724249),
])
def test_parse_target(value, expected):
    assert parse_target(value) == expected


@pytest.mark.parametrize("value", ["", "not-an-ad", "https://pc.bazos.cz/"])
def test_parse_target_rejects_junk(value):
    with pytest.raises(CommandError):
        parse_target(value)


@pytest.mark.django_db
def test_appraise_reports_the_ad_and_its_comparables(scored):
    subject = scored(61000, name="MacBook 14 M4 Max")
    scored(65000, name="MacBook Pro 14 M4 Max")

    out = StringIO()
    call_command("appraise", str(subject.external_id), stdout=out)
    report = out.getvalue()

    assert "MacBook 14 M4 Max" in report
    assert 'M4 Max 36GB/1TB 14"' in report
    assert "65000" in report
    assert "rank 1 of 2" in report
    assert "asking prices, not sold" in report


@pytest.mark.django_db
def test_appraise_errors_on_an_unknown_ad(db):
    with pytest.raises(CommandError, match="No ad with external_id"):
        call_command("appraise", "999999999", stdout=StringIO())


@pytest.mark.django_db
def test_appraise_reports_a_decline_reason(scored):
    subject = scored(61000, declined=True)

    out = StringIO()
    call_command("appraise", str(subject.external_id), stdout=out)

    assert "DECLINED" in out.getvalue()


@pytest.mark.django_db
def test_appraise_measures_distance_from_an_explicit_origin(scored, praha_brno):
    subject = scored(61000)
    Ad.objects.filter(pk=subject.pk).update(location="Brno, 602 00")

    out = StringIO()
    call_command("appraise", str(subject.external_id), "--from", "110 00", stdout=out)

    assert "km from 11000" in out.getvalue()


@pytest.mark.django_db
def test_appraise_falls_back_to_the_query_that_watched_the_ad(
    scored, query, make_delivery, praha_brno
):
    """Without --from, the useful origin is the one that actually decided delivery — which
    means the ad has to have a delivery for that query, not merely have been found by it."""
    query.filter_location_center = "11000"
    query.filter_location_radius = 40
    query.save()
    subject = scored(61000)
    Ad.objects.filter(pk=subject.pk).update(location="Brno, 602 00")
    make_delivery(subject, query)

    out = StringIO()
    call_command("appraise", str(subject.external_id), stdout=out)

    assert "km from 11000" in out.getvalue()


@pytest.mark.django_db
def test_appraise_omits_distance_when_there_is_no_origin(scored, praha_brno):
    """Today's default: no --from, and no query configured a distance filter. Distance is a
    property of a pair, so with only one end there is nothing honest to print."""
    subject = scored(61000)
    Ad.objects.filter(pk=subject.pk).update(location="Brno, 602 00")

    out = StringIO()
    call_command("appraise", str(subject.external_id), stdout=out)
    report = out.getvalue()

    assert "Brno, 602 00" in report
    assert "km from" not in report


@pytest.mark.django_db
def test_appraise_says_when_a_code_is_not_geocoded(scored):
    subject = scored(61000)
    Ad.objects.filter(pk=subject.pk).update(location="Pelhřimov, 394 03")

    out = StringIO()
    call_command("appraise", str(subject.external_id), "--from", "11000", stdout=out)

    assert "not geocoded" in out.getvalue()


@pytest.mark.django_db
def test_appraise_reports_price_history(scored):
    subject = scored(61000)
    PriceChange.objects.create(
        ad=subject, old_price="70 000 Kč", new_price="61 000 Kč",
        old_price_amount=70000, new_price_amount=61000,
    )

    out = StringIO()
    call_command("appraise", str(subject.external_id), stdout=out)
    report = out.getvalue()

    assert "1 price change(s)" in report
    assert "70 000 Kč -> 61 000 Kč" in report


@pytest.mark.django_db
def test_appraise_reports_unchanged_price(scored):
    out = StringIO()
    call_command("appraise", str(scored(61000).external_id), stdout=out)

    assert "unchanged since discovery" in out.getvalue()


@pytest.mark.django_db
def test_appraise_lists_deliveries_with_their_reasons(scored, query, make_delivery):
    subject = scored(61000)
    delivery = make_delivery(subject, query)
    AdDelivery.objects.filter(pk=delivery.pk).update(
        status=AdStatus.REJECTED, filter_reason="183 km away (60200), limit 40 km from 11000"
    )

    out = StringIO()
    call_command("appraise", str(subject.external_id), stdout=out)
    report = out.getvalue()

    assert f"q{query.pk} REJECTED" in report
    assert "183 km away" in report


@pytest.mark.django_db
def test_appraise_says_when_no_model_claims_the_ad(query, make_ad):
    ad = make_ad(query, 4242)    # "Ad 4242" — no registered model recognises it
    ad.save()

    out = StringIO()
    call_command("appraise", str(ad.external_id), stdout=out)

    assert "no registered model claims this ad" in out.getvalue()


@pytest.mark.django_db
def test_appraise_says_when_a_claimed_ad_was_never_scored(query, make_ad):
    ad = make_ad(query, 4243)
    ad.name = "MacBook Pro 14 M4 Max 36GB 1TB"
    ad.save()

    out = StringIO()
    call_command("appraise", str(ad.external_id), stdout=out)

    assert "claimed but never scored" in out.getvalue()


# ---------------------------------------------------------------------------
# The admin panel
# ---------------------------------------------------------------------------

@pytest.fixture
def ad_admin():
    from django.contrib.admin.sites import AdminSite

    from bazos.admin import AdAdmin
    return AdAdmin(Ad, AdminSite())


@pytest.mark.django_db
def test_admin_panel_lists_the_bucket_and_marks_this_ad(ad_admin, scored):
    subject = scored(61000)
    scored(65000)

    html = ad_admin.comparables(subject)

    # The label reaches the page through format_html, so its `"` arrives escaped.
    assert "M4 Max 36GB/1TB 14&quot;" in html
    assert "← this ad" in html
    assert "61000" in html and "65000" in html


@pytest.mark.django_db
def test_admin_panel_explains_an_empty_bucket(ad_admin, query, make_ad):
    ad = make_ad(query, 1)
    ad.save()

    assert "no comparable bucket" in ad_admin.comparables(ad)


@pytest.mark.django_db
def test_admin_panel_handles_an_unsaved_ad(ad_admin):
    """The change form renders readonly fields on the *add* page too, where pk is None."""
    assert ad_admin.comparables(Ad()) == "—"
