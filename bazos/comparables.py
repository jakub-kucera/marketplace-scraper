"""Where one ad sits among listings of the same thing.

The hard part of "what is this worth" is not arithmetic, it is deciding what counts as the
same thing. This module does not try to solve that generally: it borrows the answer from
whichever `PriceModel` claims the ad, because a model that can predict a price already has a
vocabulary for the specs that matter, and nothing else in the codebase does.

Consequences worth knowing before using this:

- **Comparables exist only for ads a model claims and scored.** The bucket is read off the
  persisted `AdPriceScore.features`, so an ad with no score has no comparables — and so does
  every ad of a kind no model covers. That is the same coverage as `Ad.price_score_summary`,
  deliberately: the two lines appear together or not at all.
- **These are asking prices.** Nothing here records what anything sold for; see
  docs/research/MACBOOK_PRICE_MODEL.md §6. A cluster of asks is what sellers hoped for, and
  the median of it is not a market price.
- **Relisting is not deduplicated.** A dealer who lists the same machine weekly appears once
  per listing, and 56% of the MacBook corpus comes from ten dealers (§training). Treat a
  count as "listings", never as "units for sale".
"""
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

from bazos.const import COMPARABLE_MAX_AGE_DAYS, COMPARABLE_MAX_ROWS
from bazos.models import Ad, AdPriceScore, PriceType

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Comparable:
    external_id: int
    name: str
    price: int
    url: str
    is_subject: bool


@dataclass(frozen=True)
class ComparableSet:
    """Listings sharing the subject's spec bucket, cheapest first."""

    label: str
    rows: list[Comparable]

    @property
    def prices(self) -> list[int]:
        return [row.price for row in self.rows]

    @property
    def count(self) -> int:
        return len(self.rows)

    @property
    def cheapest(self) -> int:
        return self.prices[0]

    @property
    def dearest(self) -> int:
        return self.prices[-1]

    @property
    def median(self) -> int:
        prices = self.prices
        mid = len(prices) // 2
        if len(prices) % 2:
            return prices[mid]
        return (prices[mid - 1] + prices[mid]) // 2

    @property
    def subject_rank(self) -> int | None:
        """1-based position of the subject among these listings, if it is one of them."""
        for index, row in enumerate(self.rows, start=1):
            if row.is_subject:
                return index
        return None

    def summary(self) -> str:
        """The one-line form that goes into a Discord notification."""
        if self.count < 2:
            return ""
        span = (
            f"{kc(self.cheapest)}"
            if self.cheapest == self.dearest
            else f"{kc(self.cheapest)}–{kc(self.dearest)}"
        )
        line = f"Similar ({self.label}): {self.count} listed, {span}"
        rank = self.subject_rank
        if rank == 1:
            return f"{line} — this is cheapest"
        if rank is not None:
            return f"{line} — this is #{rank}"
        return line


def kc(amount: int) -> str:
    """`61000` -> `61k`. Notifications are read on a phone; four significant digits of a
    used-laptop price are noise.

    Public because the daily digest formats prices the same way, and two money formats in
    one product is one too many.
    """
    return f"{round(amount / 1000)}k"


def _bucket(score: AdPriceScore) -> dict | None:
    """The feature subset that defines "the same thing", per the model that produced `score`.

    `comparable_keys` is an optional class attribute rather than a `PriceModel` protocol
    member — the same call as `dedup_break_streak` on the scraper protocol. A model that
    predicts prices need not also have an opinion about what makes two listings comparable,
    and one that does not simply has no comparables.
    """
    from bazos.pricing.registry import MODEL_REGISTRY

    model = MODEL_REGISTRY.get(score.model_name)
    keys = getattr(model, "comparable_keys", None)
    if model is None or not keys:
        return None
    features = score.features or {}
    bucket = {key: features.get(key) for key in keys}
    # A bucket with a hole in it matches every ad missing that same spec, which is a
    # different question from "the same machine". Decline instead.
    if any(value is None for value in bucket.values()):
        return None
    return bucket


def _label(score: AdPriceScore, bucket: dict) -> str:
    from bazos.pricing.registry import MODEL_REGISTRY

    model = MODEL_REGISTRY.get(score.model_name)
    describe = getattr(model, "describe_features", None)
    if describe is not None:
        return describe(bucket)
    return " ".join(str(value) for value in bucket.values())


def find_comparables(ad: Ad, *, subject_score: AdPriceScore | None = None) -> ComparableSet | None:
    """Listings in the same spec bucket as `ad`, cheapest first. None when undecidable.

    `subject_score` lets a caller that already loaded the score avoid a second read — the
    notification path does exactly that, since `price_score_summary` has it in hand.
    """
    score = subject_score if subject_score is not None else (
        ad.price_scores.exclude(predicted__isnull=True).order_by("-created").first()
    )
    if score is None:
        return None
    bucket = _bucket(score)
    if bucket is None:
        return None

    cutoff = timezone.now() - timedelta(days=COMPARABLE_MAX_AGE_DAYS)
    matches = (
        AdPriceScore.objects
        .filter(model_name=score.model_name, ad__created__gte=cutoff,
                ad__price_type=PriceType.EXACT, ad__price__gt=0,
                **{f"features__{key}": value for key, value in bucket.items()})
        .select_related("ad")
        .order_by("ad__price")[:COMPARABLE_MAX_ROWS]
    )
    rows = []
    for match in matches:
        price = match.ad.price
        if price is None:  # already excluded by `price__gt=0`; narrows the Optional
            continue
        rows.append(
            Comparable(
                external_id=match.ad.external_id,
                name=match.ad.name,
                price=price,
                url=match.ad.url,
                is_subject=match.ad_id == ad.pk,
            )
        )
    if not rows:
        return None
    return ComparableSet(label=_label(score, bucket), rows=rows)
