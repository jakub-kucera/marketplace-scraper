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
