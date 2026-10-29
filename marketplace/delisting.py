"""Which ads are due a liveness check, and what to write down when one comes back.

The point of this module is the *only* outcome data the project has. Every price figure it
holds is an **asking** price; `Ad.removed_at` is the closest available proxy for a listing
having actually gone, and paired with the last-seen price it is what lets a question like
"do the model's picks disappear faster than average" be asked at all.

Two things it is careful about, both of which are easy to get wrong in ways that silently
corrupt that dataset:

- **A failed request is not a removal.** Tor 403s about half of all attempts here; a sweep
  that treated "no response" as "gone" would write thousands of false deaths in one bad
  hour, into the one table meant to hold truth. Only a *successful* response whose payload
  omits an id counts as evidence.
- **Removed is not sold.** Bazos listings expire on their own, so past
  `DELIST_MAX_AGE_DAYS` an ad stops being watched and its `removed_at` stays NULL — a
  censored observation, not a claim that it is still for sale.
"""
import logging
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Q, QuerySet
from django.utils import timezone

from marketplace.const import (
    DELIST_MAX_AGE_DAYS,
    DELIST_PRIORITY_SPEEDUP,
    DELIST_SCHEDULE,
)
from marketplace.models import Ad, AdDelivery, AdStatus, Marketplace

logger = logging.getLogger(__name__)

#: Only these have a bulk id endpoint. Vinted and Sbazar would need one request per ad,
#: which inverts the economics that make this affordable at all — see CLAUDE.md.
SWEEPABLE_MARKETPLACES = (Marketplace.BAZOS, Marketplace.BAZOS_API)


@dataclass(frozen=True)
class SweepResult:
    checked: int = 0
    still_listed: int = 0
    newly_removed: int = 0
    price_changes: int = 0
    batches_failed: int = 0

    def __str__(self) -> str:
        return (
            f"checked {self.checked}, still listed {self.still_listed}, "
            f"newly removed {self.newly_removed}, price changes {self.price_changes}, "
            f"failed batches {self.batches_failed}"
        )


def recheck_interval_days(age_days: float, *, priority: bool = False) -> int | None:
    """How long to wait before re-checking an ad of this age. None = stop watching it.

    Ascending scan of `DELIST_SCHEDULE`, so the first band the age falls into wins.
    """
    for max_age, interval in DELIST_SCHEDULE:
        if age_days < max_age:
            if priority:
                return max(1, interval // DELIST_PRIORITY_SPEEDUP)
            return interval
    return None


def due_for_check(now=None) -> QuerySet[Ad]:
    """Live, sweepable ads whose next check is due, oldest check first.

    The age bands are expressed as one `Q` per band rather than evaluated in Python because
    the candidate set is the whole live corpus — tens of thousands of rows — and only a few
    hundred are ever due.

    `last_seen_at IS NULL` means never swept, which is due immediately: that is what makes
    the first run a backfill without needing a separate code path.
    """
    now = now or timezone.now()
    horizon = now - timedelta(days=DELIST_MAX_AGE_DAYS)

    due = Q()
    previous_max_age = 0
    for max_age, interval in DELIST_SCHEDULE:
        band = Q(
            created__lte=now - timedelta(days=previous_max_age),
            created__gt=now - timedelta(days=max_age),
        )
        # A priority ad is due sooner, so test it against the shortened interval.
        fast = max(1, interval // DELIST_PRIORITY_SPEEDUP)
        stale = Q(last_seen_at__isnull=True) | Q(last_seen_at__lte=now - timedelta(days=interval))
        stale_fast = Q(last_seen_at__isnull=True) | Q(last_seen_at__lte=now - timedelta(days=fast))
        due |= band & ((stale & ~Q(_priority=True)) | (stale_fast & Q(_priority=True)))
        previous_max_age = max_age

    return (
        Ad.objects
        .filter(marketplace__in=SWEEPABLE_MARKETPLACES, removed_at__isnull=True, created__gt=horizon)
        .annotate(_priority=_priority_expression())
        .filter(due)
        .order_by("last_seen_at")
    )


def _priority_expression():
    """True for ads that were notified or scored — the ones whose outcome calibrates.

    They are checked one tier faster. They are NOT the only ones checked: without the
    un-notified ads there is no baseline to compare "disappeared quickly" against, and the
    whole schedule exists so that watching everything is affordable.
    """
    from django.db.models import Exists, OuterRef

    sent = AdDelivery.objects.filter(ad=OuterRef("pk"), status=AdStatus.SENT)
    from marketplace.models import AdPriceScore

    scored = AdPriceScore.objects.filter(ad=OuterRef("pk"), predicted__isnull=False)
    return Exists(sent) | Exists(scored)


def apply_batch(ads: list[Ad], found: dict[int, dict], now=None) -> SweepResult:
    """Record one batch's outcome. `found` is keyed by external_id; absence means removed.

    Callers must only pass `found` from a **successful** response. An empty dict here is
    read as "every one of these is gone", which is correct after a 200 that returned no
    rows and catastrophic after a timeout.
    """
    from marketplace.filters import parse_price_and_type
    from marketplace.models import PriceChange

    now = now or timezone.now()
    still_listed: list[int] = []
    removed: list[int] = []
    price_changes = 0

    for ad in ads:
        row = found.get(ad.external_id)
        if row is None:
            removed.append(ad.pk)
            continue
        still_listed.append(ad.pk)
        price_raw = (row.get("price_formatted") or "").strip()
        if price_raw and price_raw != ad.price_raw:
            amount, price_type = parse_price_and_type(price_raw)
            PriceChange.objects.create(
                ad=ad,
                old_price=ad.price_raw, new_price=price_raw,
                old_price_amount=ad.price, new_price_amount=amount,
            )
            # Same fan-out the scrape walk performs, and for the same reason: a price change
            # is a fact about the ad, so every query watching it re-enters the filter.
            AdDelivery.objects.filter(ad=ad).update(status=AdStatus.PRICE_CHANGED)
            ad.price_raw, ad.price, ad.price_type = price_raw, amount, price_type
            ad.save(update_fields=["price_raw", "price", "price_type"])
            price_changes += 1

    if still_listed:
        Ad.objects.filter(pk__in=still_listed).update(last_seen_at=now)
    if removed:
        Ad.objects.filter(pk__in=removed).update(last_seen_at=now, removed_at=now)

    return SweepResult(
        checked=len(ads),
        still_listed=len(still_listed),
        newly_removed=len(removed),
        price_changes=price_changes,
    )
