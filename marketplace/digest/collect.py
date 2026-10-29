"""Gather the daily digest's numbers. The only impure half.

Two clocks here, deliberately not reconciled — say so before someone "fixes" one:

* **Headline counts and the drops list use a rolling 24 h** ending at run time. Fired at
  13:00, a calendar "today" would be half a day, and a headline saying "2 431 new ads"
  about thirteen hours is a lie the reader cannot detect.
* **The 14-day charts and archive gaps keep calendar days**, because that is what
  `charts.series` and `admin_market._archive` already mean, and `_archive` already excludes
  today for the same reason.

The footer states the window, because with `catch_up: False` a slot missed while the Pi was
down fires once on return — the digest can arrive at 16:40 and must not imply otherwise.
"""
from dataclasses import dataclass, field
from datetime import timedelta

from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from marketplace.charts import CHART_DAYS, series
from marketplace.health import Anomaly, anomalies

#: Drops steeper than this are relists, typos or bait, not bargains. Measured 2026-09-20:
#: a 60% gate removes ~1 of 288 daily drops — but the list is the *top* 8 by percentage,
#: which is exactly where that one lives (a phone "dropped" 35 990 → 1 000).
DROP_MAX_PCT = 60
#: A 200 → 80 move is 60% off and worth nothing; without this it outranks every real find.
MIN_OLD_PRICE_CZK = 1_000
#: The absolute floor, so 12% off a 60k laptop qualifies and 12% off a 1.2k item does not.
MIN_DROP_CZK = 500

MAX_DROP_ROWS = 8
MAX_FLAG_ROWS = 5


@dataclass(frozen=True)
class Drop:
    name: str
    url: str
    marketplace: str
    old: int
    new: int
    pct: float


@dataclass(frozen=True)
class Flag:
    name: str
    url: str
    price: int
    predicted: int
    z_score: float
    notified: bool


@dataclass(frozen=True)
class DigestData:
    """Everything the renderer needs, and nothing that needs a database."""

    generated: object
    window_hours: int
    found: int
    found_avg: float
    notified: int
    notified_avg: float
    rejected: int
    delisted: int
    drops_down: int
    drops_up: int
    latency_median: float | None
    latency_p90: float | None
    fail_rate: int | None
    fail_baseline: int | None
    ads_labels: list = field(default_factory=list)
    ads_values: list = field(default_factory=list)
    drop_labels: list = field(default_factory=list)
    drop_values: list = field(default_factory=list)
    rise_values: list = field(default_factory=list)
    drops: list = field(default_factory=list)
    flags: list = field(default_factory=list)
    anomalies: list = field(default_factory=list)


def _plausible_drops(since):
    """Biggest real drops, one row per ad, bait gated out.

    Collapsing per ad matters: one listing can write several `PriceChange` rows in a day,
    and a flip-flop would otherwise occupy three of the eight slots with the same item.
    `max(old) → min(new)` reports its net move once.

    Vinted is excluded upstream of the gate — `CROSS_MARKETPLACE_MACBOOK.md` §5.4 found its
    prices are PLN converted at a drifting daily rate, which manufactures changes nobody made.
    """
    from marketplace.models import Marketplace, PriceChange

    per_ad: dict = {}
    rows = (
        PriceChange.objects
        .exclude(ad__marketplace=Marketplace.VINTED)
        .filter(created__gte=since, old_price_amount__isnull=False, new_price_amount__isnull=False)
        .select_related("ad")
    )
    for change in rows:
        old, new = change.old_price_amount, change.new_price_amount
        if not old or new is None:
            continue
        current = per_ad.get(change.ad_id)
        per_ad[change.ad_id] = (
            change.ad,
            max(old, current[1]) if current else old,
            min(new, current[2]) if current else new,
        )

    drops = []
    for ad, old, new in per_ad.values():
        if new >= old or old < MIN_OLD_PRICE_CZK or (old - new) < MIN_DROP_CZK:
            continue
        pct = 100 * (1 - new / old)
        if pct > DROP_MAX_PCT:
            continue
        drops.append(Drop(ad.name, ad.url, ad.marketplace, old, new, round(pct, 1)))
    drops.sort(key=lambda d: -d.pct)
    return drops[:MAX_DROP_ROWS]


def _flags(since):
    """Deals the price model would have alerted on, if it were not in shadow mode.

    Ordered by z, not discount: a flat percentage is ~1σ for a private seller and ~3σ for a
    dealer, which is the whole point of the z-score. The notified flag is the shadow-mode
    decision input — a flag nobody heard about is what enabling the rule would add.
    """
    from marketplace.models import AdDelivery, AdPriceScore, AdStatus

    scores = list(
        AdPriceScore.objects.filter(z_score__lte=-2, created__gte=since)
        .select_related("ad").order_by("z_score")[:MAX_FLAG_ROWS]
    )
    if not scores:
        return []
    sent = set(
        AdDelivery.objects.filter(ad_id__in=[s.ad_id for s in scores], status=AdStatus.SENT)
        .values_list("ad_id", flat=True)
    )
    # `z_score` is nullable on the model (a declined score writes null numbers), but the
    # filter above already excludes those; the `or 0` is for mypy, not for reality.
    return [
        Flag(score.ad.name, score.ad.url, score.ad.price or 0, score.predicted or 0,
             score.z_score or 0.0, score.ad_id in sent)
        for score in scores
    ]


def collect(now=None):
    from marketplace.admin_market import _archive, _latency, _price_drops
    from marketplace.dashboard import _marketplace_health
    from marketplace.models import Ad, AdDelivery, AdStatus

    now = now or timezone.now()
    today = timezone.localdate()
    since = now - timedelta(hours=24)
    week_ago = now - timedelta(days=7)
    chart_start = now - timedelta(days=CHART_DAYS - 1)

    ads = Ad.objects.aggregate(
        day=Count("id", filter=Q(created__gte=since)),
        week=Count("id", filter=Q(created__gte=week_ago)),
        delisted=Count("id", filter=Q(removed_at__gte=since)),
    )
    deliveries = AdDelivery.objects.aggregate(
        notified=Count("id", filter=Q(sent_at__gte=since)),
        notified_week=Count("id", filter=Q(sent_at__gte=week_ago)),
        rejected=Count("id", filter=Q(created__gte=since, status=AdStatus.REJECTED)),
    )

    ad_rows = (
        Ad.objects.filter(created__gte=chart_start)
        .annotate(day=TruncDate("created"))
        .values("day").annotate(n=Count("id")).order_by("day")
    )
    ads_labels, ads_values = series(list(ad_rows), "day", CHART_DAYS, today)

    drops_by_day, _ = _price_drops(now)
    drop_labels, drop_values = series(
        [{"day": d, "n": counts[0]} for d, counts in drops_by_day.items()], "day", CHART_DAYS, today
    )
    _, rise_values = series(
        [{"day": d, "n": counts[1]} for d, counts in drops_by_day.items()], "day", CHART_DAYS, today
    )

    latency, _ = _latency(now, today)
    markets, _ = _marketplace_health(now, today, since, week_ago, chart_start)
    archive = _archive(today)
    busiest = max(markets, key=lambda m: m["attempts"], default=None)

    return DigestData(
        generated=timezone.localtime(now),
        window_hours=24,
        found=ads["day"],
        found_avg=round(ads["week"] / 7, 1),
        notified=deliveries["notified"],
        notified_avg=round(deliveries["notified_week"] / 7, 1),
        rejected=deliveries["rejected"],
        delisted=ads["delisted"],
        drops_down=sum(counts[0] for counts in drops_by_day.values()),
        drops_up=sum(counts[1] for counts in drops_by_day.values()),
        latency_median=latency[0]["median"] if latency else None,
        latency_p90=latency[0]["p90"] if latency else None,
        fail_rate=busiest["rate"] if busiest else None,
        fail_baseline=busiest["baseline"] if busiest else None,
        ads_labels=ads_labels,
        ads_values=ads_values,
        drop_labels=drop_labels,
        drop_values=drop_values,
        rise_values=rise_values,
        drops=_plausible_drops(since),
        flags=_flags(since),
        anomalies=anomalies(now, today, markets=markets, archive=archive),
    )


__all__ = ["DigestData", "Drop", "Flag", "Anomaly", "collect"]
