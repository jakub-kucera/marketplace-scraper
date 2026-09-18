"""Tests for `bazos/ratings.py`.

The load-bearing test here is the PII one. `ratings.php` returns reviewers' real names and
unmasked phone numbers, and the decision recorded in `SellerRatingFields` is that none of it
is stored. A decision nothing enforces is a comment.
"""
from unittest.mock import MagicMock, patch

import pytest
from django.utils import timezone

from bazos.models import EmailPublisher, PhonePublisher
from bazos.ratings import RatingCounts, fetch_seller_ratings, summarise

#: Shaped after the live sample in HIDDEN_API.md §6.4b, reviewer PII and all.
LIVE_ENTRIES = [
    {"name": "Autodraft", "email_id": "4788860", "phone": "731482686",
     "message": "vse v poradku", "type": "positive",
     "from": "Wed, 01 Jul 2026 08:45:15 +0200"},
    {"name": "Milan ", "email_id": "8476367", "phone": "720704959",
     "message": "nikdy neodeslal", "type": "negative",
     "from": "Tue, 30 Jun 2026 12:11:33 +0200"},
    {"name": "M. Navrátil", "email_id": "10350693", "phone": "",
     "message": "ok", "type": "positive",
     "from": "Wed, 27 May 2026 15:45:02 +0200"},
    {"name": "OB", "email_id": "34948", "phone": "420774919293",
     "message": "", "type": "neutral",
     "from": "Wed, 20 May 2026 13:57:04 +0200"},
]


@pytest.fixture
def publisher(db):
    return EmailPublisher.objects.create(bazos_id=4788860)


# ---------------------------------------------------------------------------
# summarise — pure, and the seam where the PII stops
# ---------------------------------------------------------------------------

def test_counts_and_date_range():
    counts = summarise(LIVE_ENTRIES)

    assert (counts.positive, counts.negative, counts.neutral) == (2, 1, 1)
    assert counts.total == 4
    assert counts.first_at.date().isoformat() == "2026-05-20"
    assert counts.last_at.date().isoformat() == "2026-07-01"


def test_no_reviewer_identity_survives_the_reduction():
    """The decision in `SellerRatingFields`, enforced. A caller holding a `RatingCounts` has
    no reviewer name, phone, id or review text left to persist even by accident."""
    counts = summarise(LIVE_ENTRIES)
    serialised = repr(counts)

    for leaked in ("720704959", "420774919293", "Navrátil", "Autodraft", "nikdy neodeslal"):
        assert leaked not in serialised
    assert not hasattr(counts, "entries")


def test_an_unknown_verdict_counts_as_neutral_and_is_logged():
    """A fourth verdict would change what "negative" is a proportion *of*, so it must not be
    folded in silently.

    caplog can't see this — the `bazos` logger has propagate=False (settings.py), so records
    never reach caplog's root-attached handler. Assert on the call instead.
    """
    with patch("bazos.ratings.logger.warning") as warning:
        counts = summarise([{"type": "spectacular", "from": "Wed, 01 Jul 2026 08:45:15 +0200"}])

    assert counts.neutral == 1
    warning.assert_called_once()


def test_an_unreadable_date_does_not_lose_the_count():
    """The counts are the part that matters; a date this cannot parse is not a reason to
    drop the verdict that came with it."""
    counts = summarise([{"type": "positive", "from": "last tuesday"}])

    assert counts.positive == 1
    assert counts.first_at is None


def test_no_entries_is_a_real_answer():
    counts = summarise([])

    assert counts.total == 0
    assert str(counts) == "no ratings"


# ---------------------------------------------------------------------------
# fetch_seller_ratings — what reaches the database
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_counts_are_stored_and_nothing_else_is(publisher):
    with patch("bazos.ratings.BazosApiScraper") as scraper_cls:
        scraper_cls.return_value.fetch_ratings.return_value = LIVE_ENTRIES
        fetch_seller_ratings(publisher, MagicMock())

    publisher.refresh_from_db()
    assert (publisher.ratings_positive, publisher.ratings_negative) == (2, 1)
    assert publisher.ratings_fetched_at is not None

    # Every column on the row, checked for reviewer PII — a future field added without
    # thinking would fail here rather than in a backup six months later.
    row = " ".join(str(value) for value in publisher.__dict__.values())
    for leaked in ("720704959", "420774919293", "Navrátil", "nikdy neodeslal"):
        assert leaked not in row


@pytest.mark.django_db
def test_the_right_query_param_is_used_for_each_publisher_type(publisher):
    phone = PhonePublisher.objects.create(bazos_id=999)

    with patch("bazos.ratings.BazosApiScraper") as scraper_cls:
        scraper_cls.return_value.fetch_ratings.return_value = []
        fetch_seller_ratings(publisher, MagicMock())
        fetch_seller_ratings(phone, MagicMock())

    used = [call.args[0] for call in scraper_cls.return_value.fetch_ratings.call_args_list]
    assert used == ["email_id", "phone_id"]


@pytest.mark.django_db
def test_a_seller_with_no_ratings_is_recorded_as_looked_at(publisher):
    """Zeroes with a timestamp means "looked, found none"; null means "nobody has looked".
    Same distinction a declined `AdPriceScore` keeps."""
    with patch("bazos.ratings.BazosApiScraper") as scraper_cls:
        scraper_cls.return_value.fetch_ratings.return_value = []
        fetch_seller_ratings(publisher, MagicMock())

    publisher.refresh_from_db()
    assert publisher.ratings_total == 0
    assert publisher.ratings_fetched_at is not None


@pytest.mark.django_db
def test_a_failed_request_raises_rather_than_storing_zeroes(publisher):
    """Writing zeroes here would turn a well-reviewed seller into an unrated one on a single
    failed request — the same shape of mistake as recording a failed delisting check as a
    removal."""
    publisher.ratings_positive = 12
    publisher.ratings_fetched_at = timezone.now()
    publisher.save()

    with patch("bazos.ratings.BazosApiScraper") as scraper_cls:
        scraper_cls.return_value.fetch_ratings.return_value = None
        with pytest.raises(RuntimeError):
            fetch_seller_ratings(publisher, MagicMock())

    publisher.refresh_from_db()
    assert publisher.ratings_positive == 12


def test_the_summary_string_leads_with_what_matters():
    counts = RatingCounts(positive=2, negative=1, neutral=1,
                          last_at=timezone.now())

    assert "2+" in str(counts) and "1-" in str(counts)
