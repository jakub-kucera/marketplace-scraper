"""Is the machine working — as functions, so two surfaces cannot disagree about it.

The admin dashboard and the daily digest both answer "what is wrong right now", and they
must answer it identically. Before this, four of these lived as local variables inside
`dashboard_callback`, reachable only by rendering a page; a digest would have had to
re-derive them, and then "stalled" would have meant one thing on the index and another in
Discord until someone noticed.

Everything here is request-free and returns plain data, so a job can call it.
"""
from dataclasses import dataclass
from datetime import timedelta

from django.db.models import Count, Q

#: The heartbeat is hourly, so silence past this is a dead cluster rather than a quiet one.
HEARTBEAT_STALE_MINUTES = 70

#: `QueryRun.error` is `f"{type(e).__name__}: {e}"`, so the class name is a prefix match.
BLOCK_ERROR = "MarketplaceBlockedError"

#: A failure rate this far above a marketplace's own 14-day median is worth a colour.
#: Absolute thresholds cannot work: 56% is normal for Bazos and an emergency for Sbazar.
ELEVATED_MARGIN_PCT = 25

#: Below this many attempts a rate is noise; only the absolute states are reported.
MIN_ATTEMPTS_FOR_RATE = 10


@dataclass(frozen=True)
class Anomaly:
    """One thing that is wrong, in a form both a page and a message can render.

    `kind` is a stable key, and it is what tests assert on — never the rendered text, which
    is prose and will be reworded.
    """

    kind: str
    severity: str        # "warn" | "alert"
    text: str


def median(values):
    ordered = sorted(values)
    if not ordered:
        return None
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def queue_state(now):
    """django-q liveness. The heartbeat schedule exists so silence is itself evidence."""
    from django.db.models import Max
    from django_q.models import OrmQ, Task

    day_ago, week_ago = now - timedelta(days=1), now - timedelta(days=7)
    tasks = Task.objects.aggregate(
        day=Count("id", filter=Q(started__gte=day_ago)),
        failed_week=Count("id", filter=Q(started__gte=week_ago, success=False)),
        last=Max("started"),
    )
    last_minutes = (now - tasks["last"]).total_seconds() / 60 if tasks["last"] else None
    return {
        "day": tasks["day"],
        "failed_week": tasks["failed_week"],
        "queued": OrmQ.objects.count(),
        "last_minutes": None if last_minutes is None else round(last_minutes),
        "stalled": last_minutes is None or last_minutes > HEARTBEAT_STALE_MINUTES,
    }


def scraper_state(now):
    """Scrape attempts in the last 24h.

    `blocked_out` is a complete shutout, not a low rate: roughly half of all Tor exits are
    403'd by design, so only zero successes is news.
    """
    from django.db.models import Max

    from bazos.models import QueryRun

    day_ago = now - timedelta(days=1)
    runs = QueryRun.objects.aggregate(
        attempts=Count("id", filter=Q(run_start__gte=day_ago)),
        ok=Count("id", filter=Q(run_start__gte=day_ago, success=True)),
        last_ok=Max("run_start", filter=Q(success=True)),
    )
    return {
        "attempts": runs["attempts"],
        "ok": runs["ok"],
        "pass_rate": round(100 * runs["ok"] / runs["attempts"]) if runs["attempts"] else None,
        "last_ok": runs["last_ok"],
        "blocked_out": runs["attempts"] > 0 and runs["ok"] == 0,
    }


def other_failures(since, limit=6):
    """Failures that are not blocks, named and counted.

    Small by construction — 70 rows in a week against 3 369 blocks — so grouping in Python
    beats teaching the database to split an exception string.
    """
    from bazos.models import QueryRun

    grouped: dict = {}
    rows = (
        QueryRun.objects.filter(run_start__gte=since, success=False)
        .exclude(error__startswith=BLOCK_ERROR)
        .values_list("query__marketplace", "error")
    )
    for marketplace, error in rows:
        key = (marketplace, (error or "unknown").split(":", 1)[0].strip())
        grouped[key] = grouped.get(key, 0) + 1
    return sorted(
        ({"marketplace": m, "error": e, "n": n} for (m, e), n in grouped.items()),
        key=lambda row: -row["n"],
    )[:limit]


def stalled_queries(since, limit=10):
    """Enabled queries that tried and never got through. Empty is the healthy state."""
    from bazos.models import QueryRun

    return [
        {
            "marketplace": row["query__marketplace"],
            "text": row["query__text"],
            "attempts": row["attempts"],
        }
        for row in (
            QueryRun.objects.filter(run_start__gte=since, query__enabled=True)
            .values("query__marketplace", "query__text")
            .annotate(attempts=Count("id"), ok=Count("id", filter=Q(success=True)))
            .filter(ok=0).order_by("-attempts")[:limit]
        )
    ]


def anomalies(now, today, markets=None, archive=None):
    """Everything wrong right now, worst first. Empty means healthy — say nothing.

    `markets` and `archive` can be passed in when the caller has already computed them
    (the digest has), so the same scan is not run twice.
    """
    from bazos.admin_market import _archive
    from bazos.dashboard import _marketplace_health
    from bazos.models import AdDelivery, AdStatus

    day_ago, week_ago = now - timedelta(days=1), now - timedelta(days=7)
    chart_start = now - timedelta(days=13)
    if markets is None:
        markets, _ = _marketplace_health(now, today, day_ago, week_ago, chart_start)
    if archive is None:
        archive = _archive(today)

    found: list[Anomaly] = []

    queue = queue_state(now)
    if queue["stalled"]:
        age = "never run" if queue["last_minutes"] is None else f"{queue['last_minutes']} min ago"
        found.append(Anomaly("queue_stalled", "alert", f"Cluster stalled — newest task {age}"))
    if queue["failed_week"]:
        found.append(Anomaly("queue_failures", "warn",
                             f"{queue['failed_week']} job failure(s) in 7 d"))

    for market in markets:
        if market["state"] == "silent":
            found.append(Anomaly("market_silent", "alert",
                                 f"{market['label']} silent — nothing attempted in 24 h, "
                                 f"{market['enabled']} enabled quer(ies)"))
        elif market["state"] == "down":
            found.append(Anomaly("market_down", "alert",
                                 f"{market['label']} down — {market['attempts']} attempts, "
                                 f"none succeeded"))
        elif market["state"] == "elevated":
            found.append(Anomaly("market_elevated", "warn",
                                 f"{market['label']} elevated — {market['rate']}% failing "
                                 f"vs {market['baseline']}% usual"))

    for query in stalled_queries(day_ago, limit=3):
        found.append(Anomaly("query_stalled", "warn",
                             f"Query \"{query['text'] or query['marketplace']}\" — "
                             f"{query['attempts']} attempts, 0 successes"))

    for row in archive:
        if row["gap_count"]:
            recent = ", ".join(day.strftime("%d.%m") for day in row["gaps"][-2:])
            found.append(Anomaly("archive_gap", "alert",
                                 f"{row['label']} archive gap — no successful run on {recent}"))

    failed = AdDelivery.objects.filter(status=AdStatus.FAILED, created__gte=day_ago).count()
    if failed:
        found.append(Anomaly("deliveries_failed", "alert",
                             f"{failed} notification(s) permanently failed"))

    errors = other_failures(day_ago, limit=3)
    if errors:
        rendered = ", ".join(f"{e['marketplace']} ×{e['n']} {e['error']}" for e in errors)
        found.append(Anomaly("other_errors", "warn", f"Errors that are not blocks — {rendered}"))

    found.sort(key=lambda a: (a.severity != "alert",))
    return found
