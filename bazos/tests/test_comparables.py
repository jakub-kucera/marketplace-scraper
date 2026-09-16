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
from bazos.models import Ad, AdPriceScore, PriceType
from bazos.pricing.estimators.macbook import MacbookPriceModel

M4_MAX_36_1TB = {"chip_key": "apple4_max", "ram_gb": 36, "ssd_gb": 1000, "screen": 14.0}


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
    """The score lookup short-circuits before the comparables query, so an ad nothing
    scored pays exactly what it paid before this feature.

    These fixtures attach no publisher, so `seller_ad_counts` short-circuits to zero
    queries — which is the point: it isolates the cost this feature adds. The full
    identity-walk cost is pinned separately in test_seller_ad_counts.py.
    """
    ad = make_ad(query, 1)
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
