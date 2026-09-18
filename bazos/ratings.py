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
from django.utils import timezone

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
    return counts
