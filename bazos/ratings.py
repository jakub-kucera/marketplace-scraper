"""Seller reputation, reduced to counts before anything is stored.

`ratings.php` hands back every review a seller has, each carrying the **reviewer's** real
name, unmasked phone number and free-text message. This module is the seam where that stops:
`summarise()` takes the raw entries and returns five numbers and two dates, and nothing else
in the project ever sees the rest.

That the reduction happens in a pure function with a narrow return type is the enforcement.
A future caller cannot accidentally persist a reviewer's phone number, because by the time it
has a `RatingCounts` there is no phone number left to persist. See
`SellerRatingFields` for why counts are the right answer and what is being given up.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from email.utils import parsedate_to_datetime

import requests
from django.conf import settings
from django.db import transaction
from django.utils import timezone

from bazos.const import STORE_SELLER_REVIEWS

from bazos.scraping.bazos.bazos_api_scraper import BazosApiScraper

logger = logging.getLogger(__name__)

#: `type` values seen live (HIDDEN_API.md §6.4b). Anything else is counted as neutral and
#: logged — a marketplace inventing a fourth verdict should be visible, not silently dropped.
POSITIVE, NEGATIVE, NEUTRAL = "positive", "negative", "neutral"


@dataclass(frozen=True)
class RatingCounts:
    positive: int = 0
    negative: int = 0
    neutral: int = 0
    first_at: datetime | None = None
    last_at: datetime | None = None

    @property
    def total(self) -> int:
        return self.positive + self.negative + self.neutral

    def __str__(self) -> str:
        if not self.total:
            return "no ratings"
        recency = f", latest {self.last_at:%Y-%m-%d}" if self.last_at else ""
        return f"{self.positive}+ / {self.negative}- / {self.neutral}~{recency}"


def _parse_date(value: str | None) -> datetime | None:
    """`from` arrives as RFC 2822 ("Wed, 01 Jul 2026 08:45:15 +0200").

    Returns None rather than raising on anything unexpected: a date this cannot read is not
    a reason to lose the counts, which are the part that matters.
    """
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        logger.warning("Unparseable rating date %r", value)
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)


def summarise(entries: list[dict]) -> RatingCounts:
    """Reduce raw `ratings.php` entries to counts and a date range. Pure; stores nothing.

    Everything not in the return type — `name`, `phone`, `email_id`, `message` — is dropped
    here and never reaches a caller.
    """
    tally = {POSITIVE: 0, NEGATIVE: 0, NEUTRAL: 0}
    dates: list[datetime] = []

    for entry in entries:
        verdict = str(entry.get("type", "")).strip().lower()
        if verdict not in tally:
            # Not silently folded in without a word: a fourth verdict would change what
            # "negative" is a proportion *of*, and that should be noticed.
            logger.warning("Unknown rating type %r; counting as neutral", verdict)
            verdict = NEUTRAL
        tally[verdict] += 1
        when = _parse_date(entry.get("from"))
        if when is not None:
            dates.append(when)

    return RatingCounts(
        positive=tally[POSITIVE],
        negative=tally[NEGATIVE],
        neutral=tally[NEUTRAL],
        first_at=min(dates) if dates else None,
        last_at=max(dates) if dates else None,
    )


def store_reviews(publisher, entries: list[dict]) -> int:
    """Persist the review text for one publisher, replacing whatever was there.

    Delete-and-replace rather than upsert, because the endpoint returns the seller's whole
    history unpaginated: the response is the truth, so a review edited or withdrawn upstream
    should vanish here too. See `SellerReview` for why there is no natural key to upsert on.

    Returns the number of rows written. Does nothing and returns 0 unless
    `STORE_SELLER_REVIEWS` is on - the counts in `fetch_seller_ratings` are the always-on
    answer, and this is the deliberate widening `SellerRatingFields` describes.
    """
    from bazos.models import SellerReview

    if not getattr(settings, "STORE_SELLER_REVIEWS", STORE_SELLER_REVIEWS):
        return 0

    field = "email_publisher" if publisher.ratings_param == "email_id" else "phone_publisher"
    rows = [
        SellerReview(
            **{field: publisher},
            reviewer_external_id=str(entry.get("email_id") or "")[:32],
            reviewer_name=str(entry.get("name") or "").strip()[:120],
            reviewer_phone=str(entry.get("phone") or "").strip()[:30],
            verdict=(str(entry.get("type", "")).strip().lower()
                     if str(entry.get("type", "")).strip().lower() in (POSITIVE, NEGATIVE, NEUTRAL)
                     else NEUTRAL),
            message=str(entry.get("message") or ""),
            rated_at=_parse_date(entry.get("from")),
        )
        for entry in entries
    ]
    with transaction.atomic():
        # Both inside one transaction: a crash between them would leave the seller looking
        # unreviewed, which reads as "nobody has reviewed" rather than "we lost it".
        SellerReview.objects.filter(**{field: publisher}).delete()
        SellerReview.objects.bulk_create(rows)
    return len(rows)


def fetch_seller_ratings(publisher, session: requests.Session) -> RatingCounts:
    """Read one publisher id's ratings and store the counts on its row.

    Raises on "no usable answer" rather than writing zeroes: a failed request must not turn
    a well-reviewed seller into an unrated one, which is the same shape of mistake as
    recording a failed delisting request as a removal.

    An empty list is not a failure — plenty of sellers genuinely have no ratings — so it is
    stored, with `ratings_fetched_at` set. Zeroes with a timestamp means "looked, found
    none"; null means "nobody has looked".
    """
    scraper = BazosApiScraper(session)
    entries = scraper.fetch_ratings(publisher.ratings_param, publisher.bazos_id)
    if entries is None:
        raise RuntimeError(
            f"no usable ratings response for {publisher.ratings_param}={publisher.bazos_id}"
        )

    counts = summarise(entries)
    publisher.ratings_positive = counts.positive
    publisher.ratings_negative = counts.negative
    publisher.ratings_neutral = counts.neutral
    publisher.ratings_first_at = counts.first_at
    publisher.ratings_last_at = counts.last_at
    publisher.ratings_fetched_at = timezone.now()
    publisher.save(update_fields=[
        "ratings_positive", "ratings_negative", "ratings_neutral",
        "ratings_first_at", "ratings_last_at", "ratings_fetched_at",
    ])
    stored = store_reviews(publisher, entries)
    if stored:
        logger.info("Stored %d review(s) for %s=%s", stored, publisher.ratings_param, publisher.bazos_id)
    return counts
