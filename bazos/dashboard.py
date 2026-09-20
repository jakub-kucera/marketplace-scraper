"""The admin index dashboard.

Five questions, in the order you would ask them when something feels wrong. Every panel
here earns its place by answering one of them; a number that is merely interesting belongs
on a changelist, because this page is rendered on every visit to `/admin/`.

1. **Is the queue alive?** The hourly heartbeat is the liveness signal — if the newest task
   is older than an hour, the cluster is down, whatever the other panels say.
2. **Is the scraper getting through?** Roughly half of all Tor exits are 403'd by Bazos, so
   a per-attempt success rate near 50% is *healthy*; zero is not, and that distinction is
   the whole point of showing attempts alongside successes.
3. **Is the pipeline draining?** `PENDING` and `APPROVED` are queues in Postgres. Steady
   small numbers are normal; a growing one means `run_filter` or `run_sender` is wedged.
4. **Are we still finding ads?** The 14-day bar chart is the zero-rows canary in a form you
   can see before it fires.
5. **Is outcome data accumulating?** `AdOutcome` is the only ground truth about a sale, and
   it only fills up if a human fills it. A counter sitting at zero is the nudge.
6. **Which marketplace is unhealthy?** Not "what is the failure rate" — that number is
   meaningless pooled. Measured 2026-09-20 over 7 days: Bazos 56% of attempts failed and
   was fine, Vinted 31% and was broken. Blocks are a *cost* the retry loop absorbs; a
   `RuntimeError` is a contract break no retry fixes. So health is judged per marketplace,
   against that marketplace's own recent history, and blocks are demoted everywhere.

Cost: eight aggregate queries, none of them per-row. `_ONE_QUERY_PER_TABLE` is the rule —
conditional aggregation rather than a query per number — because this runs on a Raspberry
Pi behind every admin page load.
"""

from datetime import timedelta

from django.db.models import Avg, Count, F, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

# Chart shapes and health states live outside this module because the daily Discord digest
# answers the same questions and must not answer them differently. This page is one
# consumer of them, not their owner.
from bazos.charts import CHART_DAYS, Series, chart_json, series
from bazos.health import (
    BLOCK_ERROR,
    ELEVATED_MARGIN_PCT,
    MIN_ATTEMPTS_FOR_RATE,
    median,
    other_failures,
    queue_state,
    scraper_state,
    stalled_queries,
)


def humanise_duration(delta):
    """`0:16:49.285714` is not a duration anyone reads. "16m 49s" is.

    Public because the task-history changelist formats the same quantity, and two duration
    formats in one product is one too many.
    """
    if delta is None:
        return "—"
    total = delta.total_seconds()
    if total < 10:
        # The heartbeat takes ~0.4 s. Rounding that to "0s" reads like a broken column.
        return f"{total:.1f}s"
    if total < 60:
        return f"{int(total)}s"
    return f"{int(total) // 60}m {int(total) % 60:02d}s"


def _marketplace_health(now, today, day_ago, week_ago, chart_start):
    """Per-marketplace state, judged against each marketplace's own trailing median.

    Four states, each a distinct failure mode rather than a band of one number:

    * **silent** — enabled queries but nothing even attempted in 24h. The runner is stuck,
      or every query on it is disabled by something upstream. Worse than failing.
    * **down** — attempted and not one attempt succeeded. For Bazos that takes a shutout
      across `MAX_BLACKLIST_RETRIES` rotations; for Vinted one broken endpoint does it.
    * **elevated** — succeeding, but failing much more than it usually does.
    * **ok**.
    """
    from django.db.models import Case, Count, IntegerField, Q, When

    from bazos.models import Ad, Marketplace, Query, QueryRun

    queries = {
        row["marketplace"]: row
        for row in Query.objects.values("marketplace").annotate(
            enabled=Count("id", filter=Q(enabled=True)), total=Count("id")
        )
    }
    ads = {
        row["marketplace"]: row["n"]
        for row in Ad.objects.filter(created__gte=week_ago)
        .values("marketplace").annotate(n=Count("id"))
    }

    # One query feeds the cards, the baselines and the chart: attempts per marketplace per
    # day, split into blocked / other / succeeded.
    daily = list(
        QueryRun.objects.filter(run_start__gte=chart_start)
        .annotate(
            day=TruncDate("run_start"),
            marketplace=F("query__marketplace"),
            blocked=Case(
                When(success=False, error__startswith=BLOCK_ERROR, then=1),
                default=0, output_field=IntegerField(),
            ),
        )
        .values("day", "marketplace", "blocked")
        .annotate(attempts=Count("id"), ok=Count("id", filter=Q(success=True)))
        .order_by("day")
    )

    per_market: dict[str, dict] = {}
    for row in daily:
        bucket = per_market.setdefault(row["marketplace"], {})
        day = bucket.setdefault(row["day"], {"attempts": 0, "ok": 0, "blocked": 0})
        day["attempts"] += row["attempts"]
        day["ok"] += row["ok"]
        if row["blocked"]:
            day["blocked"] += row["attempts"]

    cards = []
    for value, label in Marketplace.choices:
        counts = queries.get(value, {"enabled": 0, "total": 0})
        if not counts["total"]:
            continue
        days = per_market.get(value, {})
        recent = days.get(today, {"attempts": 0, "ok": 0})
        yesterday = days.get(today - timedelta(days=1), {"attempts": 0, "ok": 0})
        attempts = recent["attempts"] + yesterday["attempts"]
        ok = recent["ok"] + yesterday["ok"]
        rate = round(100 * (attempts - ok) / attempts) if attempts else None
        # The baseline deliberately excludes today: comparing a partial day against a
        # window that contains it drags the reference toward the very thing being judged.
        history = [
            round(100 * (d["attempts"] - d["ok"]) / d["attempts"])
            for day, d in days.items()
            if day < today and d["attempts"] >= MIN_ATTEMPTS_FOR_RATE
        ]
        baseline = median(history)

        if counts["enabled"] and not attempts:
            state = "silent"
        elif attempts and not ok:
            state = "down"
        elif (
            attempts >= MIN_ATTEMPTS_FOR_RATE
            and baseline is not None
            and rate is not None
            and rate > baseline + ELEVATED_MARGIN_PCT
        ):
            state = "elevated"
        else:
            state = "ok"

        cards.append({
            "label": label,
            "enabled": counts["enabled"],
            "total": counts["total"],
            "attempts": attempts,
            "rate": rate,
            "baseline": None if baseline is None else round(baseline),
            "ads_week": ads.get(value, 0),
            "state": state,
        })
    return cards, per_market


def dashboard_callback(request, context):
    from django_q.models import Task

    from bazos.jobs import HEARTBEAT, JOB_CATALOG
    from bazos.models import Ad, AdDelivery, AdOutcome, AdStatus

    now = timezone.now()
    today = timezone.localdate()
    day_ago, week_ago = now - timedelta(days=1), now - timedelta(days=7)
    chart_start = now - timedelta(days=CHART_DAYS - 1)

    # 1. queue, 2. scraper -----------------------------------------------------
    # Both from `bazos.health`, so "stalled" and "blocked out" mean the same thing here as
    # they do in the daily digest.
    queue = queue_state(now)
    scraper = scraper_state(now)

    # 3. pipeline --------------------------------------------------------------
    by_status = {
        row["status"]: row["n"]
        for row in AdDelivery.objects.values("status").annotate(n=Count("id"))
    }
    # Failures are counted over a week, not all time. An all-time total reads as a
    # monument — 65 accumulated over six weeks and looked like history until someone
    # checked the dates. A recent count means "this is happening now".
    failed_week = AdDelivery.objects.filter(
        status=AdStatus.FAILED, created__gte=week_ago
    ).count()

    # 4. discovery -------------------------------------------------------------
    ads = Ad.objects.aggregate(
        day=Count("id", filter=Q(created__gte=day_ago)),
        week=Count("id", filter=Q(created__gte=week_ago)),
        watched=Count("id", filter=Q(removed_at__isnull=True, last_seen_at__isnull=False)),
        removed_week=Count("id", filter=Q(removed_at__gte=week_ago)),
    )
    ad_rows = (
        Ad.objects.filter(created__gte=chart_start)
        .annotate(day=TruncDate("created")).values("day")
        .annotate(n=Count("id")).order_by("day")
    )
    ad_labels, ad_values = series(list(ad_rows), "day", CHART_DAYS, today)

    # 5. outcomes --------------------------------------------------------------
    outcomes = AdOutcome.objects.count()

    # Job runs per day, split by outcome — one query, two datasets. The heartbeat is
    # excluded: at hourly it is ~24 bars a day of nothing happening, which flattens the
    # real work and hides a failure next to it. Liveness is the Queue card's job.
    task_rows = list(
        Task.objects.filter(started__gte=chart_start).exclude(func=HEARTBEAT)
        .annotate(day=TruncDate("started")).values("day", "success")
        .annotate(n=Count("id")).order_by("day")
    )
    ok_labels, ok_values = series([r for r in task_rows if r["success"]], "day", CHART_DAYS, today)
    _, fail_values = series([r for r in task_rows if not r["success"]], "day", CHART_DAYS, today)

    # 6. marketplace health ----------------------------------------------------
    markets, per_market = _marketplace_health(now, today, day_ago, week_ago, chart_start)

    # Failures per day, blocked vs everything else. Two series rather than one per
    # marketplace: eight lines is unreadable, and the split that matters is not *which*
    # marketplace failed but *whether the failure was the expected kind*. A single
    # RuntimeError has to be visible beside three thousand blocks, so the marketplace
    # detail lives in the cards and in `other_failures` below, where it can be named.
    blocked_by_day: dict = {}
    other_by_day: dict = {}
    for market_days in per_market.values():
        for day, counts in market_days.items():
            failed = counts["attempts"] - counts["ok"]
            blocked_by_day[day] = blocked_by_day.get(day, 0) + counts["blocked"]
            other_by_day[day] = other_by_day.get(day, 0) + failed - counts["blocked"]
    fail_labels, blocked_values = series(
        [{"day": d, "n": n} for d, n in blocked_by_day.items()], "day", CHART_DAYS, today
    )
    _, other_values = series(
        [{"day": d, "n": n} for d, n in other_by_day.items()], "day", CHART_DAYS, today
    )

    # The alarm list is empty in the healthy state, so the panel hides itself rather than
    # showing a reassuring zero.
    errors = other_failures(week_ago, limit=6)
    stalled = stalled_queries(day_ago, limit=10)

    slowest = (
        Task.objects.filter(started__gte=week_ago, stopped__isnull=False)
        .exclude(func=HEARTBEAT)
        .annotate(seconds=F("stopped") - F("started"))
        .values("func").annotate(avg=Avg("seconds"), n=Count("id"))
        .order_by("-avg")[:5]
    )

    context.update(
        {
            "queue": queue,
            "scraper": scraper,
            "pipeline": {
                "pending": by_status.get(AdStatus.PENDING, 0),
                "approved": by_status.get(AdStatus.APPROVED, 0),
                "failed": failed_week,
                "failed_all_time": by_status.get(AdStatus.FAILED, 0),
                "sent": by_status.get(AdStatus.SENT, 0),
            },
            "discovery": {
                "day": ads["day"],
                "week": ads["week"],
                "watched": ads["watched"],
                "removed_week": ads["removed_week"],
                "outcomes": outcomes,
            },
            "ads_chart": chart_json(ad_labels, [Series("primary", "New ads", ad_values)]),
            "tasks_chart": chart_json(ok_labels, [
                Series("primary", "Succeeded", ok_values),
                Series("danger", "Failed", fail_values),
            ]),
            "markets": markets,
            "failures_chart": chart_json(fail_labels, [
                # Blocked is drawn first and muted: it is the floor, not the signal.
                Series("muted", "Blocked (expected)", blocked_values, stack="f"),
                Series("danger", "Other errors", other_values, stack="f"),
            ]),
            "other_failures": errors,
            "stalled_queries": stalled,
            "slowest_jobs": [
                {
                    "label": JOB_CATALOG[row["func"]].label if row["func"] in JOB_CATALOG else row["func"],
                    "runs": row["n"],
                    "average": humanise_duration(row["avg"]),
                }
                for row in slowest
            ],
        }
    )
    return context
