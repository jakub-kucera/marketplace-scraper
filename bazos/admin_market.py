"""The admin's "Market" page — the data asset and the market, not the machine.

The index answers *is it running*. This answers *is it worth running*, which is a different
question with a different cadence of looking at it. Three sections, each tied to a claim in
[`docs/MONETIZATION.md`](../docs/MONETIZATION.md):

1. **Latency.** §1 calls cutting it "still the highest-return change in the repository" and
   measures a 42-minute cycle. Nothing instrumented it, so nobody could tell whether the
   API cutover — which has reached one of twelve enabled queries — is paying off. Cycle
   time is the gap between consecutive *successful* runs of the same query: sleep plus
   pass duration, which is what a buyer actually waits through. Broken out per
   marketplace, so `bazos_api` sits next to `bazos` and the cutover either shows or does
   not.
2. **Price drops.** ~60 `PriceChange` rows a day, ~70% of them downward, and nothing has
   ever looked at them. This is the one buy signal that needs no model, no calibration and
   no extra scraping. **Vinted is excluded**: `CROSS_MARKETPLACE_MACBOOK.md` §5.4 found
   ~73% of its corpus is a PLN price converted at a drifting daily rate, which manufactures
   `PriceChange` rows for listings nobody edited.
3. **Archive continuity.** §1 again: the asset is "a multi-year price/velocity archive of a
   market that deletes itself every 2 months". A day with no ads on a marketplace that
   normally produces them is a **permanent hole** — the source is gone by the time anyone
   notices. So the panel is built around gaps rather than growth: the absence is the
   finding, and it is the only chart here whose value is in what is missing.

Heavier than the index deliberately — this is a page you open, not one that loads on every
admin visit.
"""
import statistics
from datetime import timedelta
from typing import Any

from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Max, Min, Q, Window
from django.db.models.functions import Lag, TruncDate
from django.shortcuts import render
from django.utils import timezone

#: Window for the latency and drop trends.
TREND_DAYS = 14

#: Window for continuity. Long enough that a weekly rhythm is visible and a gap is not.
ARCHIVE_DAYS = 30

#: Rows in the "biggest drops" table.
TABLE_ROWS = 12

#: A day producing fewer than this fraction of a marketplace's typical output counts as a
#: hole rather than a quiet day. Deliberately generous: the claim being made is "we lost
#: data here, permanently", and a false one sends someone hunting a bug that is a weekend.
GAP_FRACTION = 0.2


def _quantiles(values):
    """(median, p90) in minutes, or (None, None). Computed here rather than in SQL.

    `percentile_cont` is an ordered-set aggregate with no ORM expression, and the input is
    a few thousand gaps — small enough that pulling them beats either raw SQL or a
    database-specific function this project would then have to keep portable.
    """
    if not values:
        return None, None
    ordered = sorted(values)
    median = statistics.median(ordered)
    p90 = ordered[min(len(ordered) - 1, int(round(0.9 * (len(ordered) - 1))))]
    return round(median, 1), round(p90, 1)


def _latency(now, today):
    """Cycle time per marketplace: the gap between consecutive successful runs of a query.

    Successful runs only, and partitioned by query. A blocked attempt is not a cycle — the
    retry loop absorbs it, and counting it would report the block rate as latency.
    """
    from bazos.models import Marketplace, QueryRun

    rows = (
        QueryRun.objects.filter(success=True, run_start__gte=now - timedelta(days=TREND_DAYS))
        .annotate(
            previous=Window(
                expression=Lag("run_start"),
                partition_by=[F("query_id")],
                order_by=F("run_start").asc(),
            )
        )
        .values("query__marketplace", "run_start", "previous")
    )

    per_market: dict[str, list] = {}
    per_day: dict[tuple, list] = {}
    for row in rows:
        if row["previous"] is None:
            continue
        minutes = (row["run_start"] - row["previous"]).total_seconds() / 60
        # A gap longer than a day is the scraper having been down, not a cycle. Including
        # it would let one outage dominate a median that exists to describe normal pacing.
        if minutes <= 0 or minutes > 24 * 60:
            continue
        market = row["query__marketplace"]
        per_market.setdefault(market, []).append(minutes)
        per_day.setdefault((market, timezone.localtime(row["run_start"]).date()), []).append(minutes)

    labels = {value: label for value, label in Marketplace.choices}
    cards = []
    for market, values in sorted(per_market.items(), key=lambda kv: -len(kv[1])):
        median, p90 = _quantiles(values)
        cards.append({
            "label": labels.get(market, market),
            "key": market,
            "median": median,
            "p90": p90,
            "cycles": len(values),
        })
    return cards, per_day


def _archive(today):
    """Per-marketplace holdings, and the days that are missing from them."""
    from bazos.models import Ad, Marketplace

    rows = (
        Ad.objects.filter(created__gte=timezone.now() - timedelta(days=ARCHIVE_DAYS))
        .annotate(day=TruncDate("created")).values("marketplace", "day")
        .annotate(n=Count("id")).order_by("day")
    )
    daily: dict[str, dict] = {}
    for row in rows:
        daily.setdefault(row["marketplace"], {})[row["day"]] = row["n"]

    totals = {
        row["marketplace"]: row
        for row in Ad.objects.values("marketplace").annotate(
            n=Count("id"), first=Min("created"), last=Max("created")
        )
    }

    labels = {value: label for value, label in Marketplace.choices}
    out = []
    for market, row in sorted(totals.items(), key=lambda kv: -kv[1]["n"]):
        days = daily.get(market, {})
        # Only days after this marketplace's first ad can be holes: Vinted and Sbazar
        # started 2026-08-23, and counting the months before that as data loss would bury
        # the real gaps in noise.
        first_local = timezone.localtime(row["first"]).date() if row["first"] else today
        window_start = max(first_local, today - timedelta(days=ARCHIVE_DAYS - 1))
        window = [window_start + timedelta(days=i) for i in range((today - window_start).days + 1)]
        counts = [days.get(day, 0) for day in window]
        typical = statistics.median(counts) if counts else 0
        gaps = [
            day for day, n in zip(window, counts)
            if typical > 0 and n < typical * GAP_FRACTION
        ]
        out.append({
            "label": labels.get(market, market),
            "total": row["n"],
            "first": row["first"],
            "last": row["last"],
            "typical": round(typical, 1),
            "gaps": gaps[-8:],
            "gap_count": len(gaps),
            "days_watched": len(window),
        })
    return out


def _price_drops(now):
    """Daily drop/rise counts and the biggest recent drops, with Vinted excluded.

    Vinted's prices are a PLN amount converted at a rate that moves daily
    (`CROSS_MARKETPLACE_MACBOOK.md` §5.4), so ~73% of its corpus generates `PriceChange`
    rows for listings nobody touched. Including them would make this panel mostly currency
    noise dressed as a buy signal.
    """
    from bazos.models import Marketplace, PriceChange

    changes = (
        PriceChange.objects
        .exclude(ad__marketplace=Marketplace.VINTED)
        .filter(old_price_amount__isnull=False, new_price_amount__isnull=False)
    )

    per_day: dict = {}
    for row in (
        changes.filter(created__gte=now - timedelta(days=TREND_DAYS))
        .annotate(day=TruncDate("created"))
        .values("day")
        .annotate(
            drops=Count("id", filter=Q(new_price_amount__lt=F("old_price_amount"))),
            rises=Count("id", filter=Q(new_price_amount__gt=F("old_price_amount"))),
        )
    ):
        per_day[row["day"]] = (row["drops"], row["rises"])

    # Narrowed in Python rather than trusted from the queryset filter: both amounts are
    # nullable, and `not old` also refuses a zero denominator — a free ad relisted at a
    # price is a 100%-of-nothing "drop" that would top this table forever.
    biggest: list[dict[str, Any]] = []
    for change in (
        changes.filter(
            created__gte=now - timedelta(days=2),
            new_price_amount__lt=F("old_price_amount"),
        ).select_related("ad").order_by("-created")[:200]
    ):
        old_amount, new_amount = change.old_price_amount, change.new_price_amount
        if not old_amount or new_amount is None:
            continue
        biggest.append({
            "ad": change.ad,
            "old": old_amount,
            "new": new_amount,
            "pct": round(100 * (1 - new_amount / old_amount), 1),
        })
    biggest.sort(key=lambda row: -row["pct"])
    return per_day, biggest[:TABLE_ROWS]


def market_view(request):
    from bazos.dashboard import CHART_DAYS, _chart, _series

    if not request.user.is_staff:
        raise PermissionDenied

    now = timezone.now()
    today = timezone.localdate()

    latency_cards, latency_by_day = _latency(now, today)
    drops_by_day, biggest_drops = _price_drops(now)
    archive = _archive(today)

    # One line per marketplace that has enough history to draw one.
    palettes = ["var(--color-primary-500)", "var(--color-base-400)",
                "var(--color-red-500)", "var(--color-blue-500)"]
    datasets = []
    labels = None
    for i, card in enumerate(latency_cards[:4]):
        rows = [
            {"day": day, "n": round(statistics.median(values), 1)}
            for (market, day), values in latency_by_day.items()
            if market == card["key"]
        ]
        labels, values = _series(rows, "day", CHART_DAYS, today)
        datasets.append({
            "label": card["label"], "data": values,
            "backgroundColor": palettes[i % len(palettes)], "borderRadius": 4,
        })

    drop_labels, drop_values = _series(
        [{"day": day, "n": counts[0]} for day, counts in drops_by_day.items()],
        "day", CHART_DAYS, today,
    )
    _, rise_values = _series(
        [{"day": day, "n": counts[1]} for day, counts in drops_by_day.items()],
        "day", CHART_DAYS, today,
    )

    return render(request, "admin/market.html", {
        **admin.site.each_context(request),
        "title": "Market",
        "latency": latency_cards,
        "latency_chart": _chart(labels or [], datasets),
        "drops_chart": _chart(drop_labels, [
            {"label": "Drops", "data": drop_values,
             "backgroundColor": "var(--color-primary-500)", "borderRadius": 4, "stack": "p"},
            {"label": "Rises", "data": rise_values,
             "backgroundColor": "var(--color-base-400)", "borderRadius": 4, "stack": "p"},
        ]),
        "biggest_drops": biggest_drops,
        "archive": archive,
        "archive_days": ARCHIVE_DAYS,
    })
