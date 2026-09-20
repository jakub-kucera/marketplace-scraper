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

import json
from datetime import timedelta

from django.db.models import Avg, Count, F, Max, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

#: How far back the trend charts look. Two weeks covers a weekend dip plus the weekly jobs.
CHART_DAYS = 14


def _series(rows, key, days, today):
    """Dense daily series — a day with no rows is a zero, not a gap.

    Chart.js joins across missing labels, so a sparse queryset would draw a line that
    implies activity on days when nothing happened.
    """
    counts = {row[key]: row["n"] for row in rows}
    start = today - timedelta(days=days - 1)
    labels, values = [], []
    for offset in range(days):
        day = start + timedelta(days=offset)
        labels.append(day.strftime("%d.%m"))
        values.append(counts.get(day, 0))
    return labels, values


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


def _chart(labels, datasets):
    """Chart.js `data`, JSON-encoded for unfold's `data-value` attribute.

    Colours are CSS variables rather than literals: unfold resolves `var(...)` at render
    time, so the chart follows the light/dark theme instead of fighting it.
    """
    return json.dumps({"labels": labels, "datasets": datasets})


#: A failure rate this many points above a marketplace's own 14-day median is worth a
#: colour. Absolute thresholds cannot work here: 56% is normal for Bazos and would be an
#: emergency for Sbazar, and a new marketplace would need a new constant on the day it
#: ships. The margin is wide because the denominator is small — one bad hour on a
#: once-a-day marketplace should not light the board up.
ELEVATED_MARGIN_PCT = 25

#: Below this many attempts a rate is noise, so only the absolute states (nothing tried,
#: nothing succeeded) are reported.
MIN_ATTEMPTS_FOR_RATE = 10

#: Prefix of the exception whose failures are expected. `QueryRun.error` is written as
#: f"{type(e).__name__}: {e}", so the class name is a prefix match — no parsing, and it
#: keeps working on any database (the suite's one SQLite caller included).
BLOCK_ERROR = "MarketplaceBlockedError"


def _median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


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
        baseline = _median(history)

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
    from django_q.models import OrmQ, Task

    from bazos.jobs import HEARTBEAT, JOB_CATALOG
    from bazos.models import Ad, AdDelivery, AdOutcome, AdStatus, QueryRun

    now = timezone.now()
    today = timezone.localdate()
    day_ago, week_ago = now - timedelta(days=1), now - timedelta(days=7)
    chart_start = now - timedelta(days=CHART_DAYS - 1)

    # 1. queue -----------------------------------------------------------------
    tasks = Task.objects.aggregate(
        day=Count("id", filter=Q(started__gte=day_ago)),
        failed_week=Count("id", filter=Q(started__gte=week_ago, success=False)),
        last=Max("started"),
    )
    queued = OrmQ.objects.count()
    last_task_age = (now - tasks["last"]).total_seconds() / 60 if tasks["last"] else None

    # 2. scraper ---------------------------------------------------------------
    runs = QueryRun.objects.aggregate(
        attempts=Count("id", filter=Q(run_start__gte=day_ago)),
        ok=Count("id", filter=Q(run_start__gte=day_ago, success=True)),
        last_ok=Max("run_start", filter=Q(success=True)),
    )
    pass_rate = round(100 * runs["ok"] / runs["attempts"]) if runs["attempts"] else None

    # 3. pipeline --------------------------------------------------------------
    by_status = {
        row["status"]: row["n"]
        for row in AdDelivery.objects.values("status").annotate(n=Count("id"))
    }

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
    ad_labels, ad_values = _series(list(ad_rows), "day", CHART_DAYS, today)

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
    ok_labels, ok_values = _series([r for r in task_rows if r["success"]], "day", CHART_DAYS, today)
    _, fail_values = _series([r for r in task_rows if not r["success"]], "day", CHART_DAYS, today)

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
    fail_labels, blocked_values = _series(
        [{"day": d, "n": n} for d, n in blocked_by_day.items()], "day", CHART_DAYS, today
    )
    _, other_values = _series(
        [{"day": d, "n": n} for d, n in other_by_day.items()], "day", CHART_DAYS, today
    )

    # Everything that is not a block, named and counted. Small by construction — 70 rows
    # in the week this was written against 3 369 blocks — so grouping it in Python is
    # cheaper than teaching the database to split an exception string.
    other_failures: dict = {}
    rows = (
        QueryRun.objects.filter(run_start__gte=week_ago, success=False)
        .exclude(error__startswith=BLOCK_ERROR)
        .values_list("query__marketplace", "error")
    )
    for marketplace, error in rows:
        key = (marketplace, (error or "unknown").split(":", 1)[0].strip())
        other_failures[key] = other_failures.get(key, 0) + 1

    # The alarm list: an enabled query that tried and never got through. Empty is the
    # healthy state, so the panel hides itself rather than showing a reassuring zero.
    stalled_queries = [
        {
            "marketplace": row["query__marketplace"],
            "text": row["query__text"],
            "attempts": row["attempts"],
        }
        for row in (
            QueryRun.objects.filter(run_start__gte=day_ago, query__enabled=True)
            .values("query__marketplace", "query__text")
            .annotate(attempts=Count("id"), ok=Count("id", filter=Q(success=True)))
            .filter(ok=0).order_by("-attempts")[:10]
        )
    ]

    slowest = (
        Task.objects.filter(started__gte=week_ago, stopped__isnull=False)
        .exclude(func=HEARTBEAT)
        .annotate(seconds=F("stopped") - F("started"))
        .values("func").annotate(avg=Avg("seconds"), n=Count("id"))
        .order_by("-avg")[:5]
    )

    context.update(
        {
            "queue": {
                "day": tasks["day"],
                "failed_week": tasks["failed_week"],
                "queued": queued,
                "last_minutes": None if last_task_age is None else round(last_task_age),
                # The heartbeat is hourly, so silence beyond ~70 minutes is a dead cluster
                # rather than a quiet one.
                "stalled": last_task_age is None or last_task_age > 70,
            },
            "scraper": {
                "attempts": runs["attempts"],
                "ok": runs["ok"],
                "pass_rate": pass_rate,
                "last_ok": runs["last_ok"],
                # Not "below 50%": half of all exits are blocked by design, so only a
                # complete shutout is news.
                "blocked_out": runs["attempts"] > 0 and runs["ok"] == 0,
            },
            "pipeline": {
                "pending": by_status.get(AdStatus.PENDING, 0),
                "approved": by_status.get(AdStatus.APPROVED, 0),
                "failed": by_status.get(AdStatus.FAILED, 0),
                "sent": by_status.get(AdStatus.SENT, 0),
            },
            "discovery": {
                "day": ads["day"],
                "week": ads["week"],
                "watched": ads["watched"],
                "removed_week": ads["removed_week"],
                "outcomes": outcomes,
            },
            "ads_chart": _chart(
                ad_labels,
                [{"label": "New ads", "data": ad_values,
                  "backgroundColor": "var(--color-primary-500)", "borderRadius": 4}],
            ),
            "tasks_chart": _chart(
                ok_labels,
                [
                    {"label": "Succeeded", "data": ok_values,
                     "backgroundColor": "var(--color-primary-500)", "borderRadius": 4},
                    {"label": "Failed", "data": fail_values,
                     "backgroundColor": "var(--color-red-500)", "borderRadius": 4},
                ],
            ),
            "markets": markets,
            "failures_chart": _chart(
                fail_labels,
                [
                    # Blocked is drawn first and muted: it is the floor, not the signal.
                    {"label": "Blocked (expected)", "data": blocked_values,
                     "backgroundColor": "var(--color-base-400)", "borderRadius": 4, "stack": "f"},
                    {"label": "Other errors", "data": other_values,
                     "backgroundColor": "var(--color-red-500)", "borderRadius": 4, "stack": "f"},
                ],
            ),
            "other_failures": sorted(
                (
                    {"marketplace": m, "error": e, "n": n}
                    for (m, e), n in other_failures.items()
                ),
                key=lambda row: -row["n"],
            )[:6],
            "stalled_queries": stalled_queries,
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
