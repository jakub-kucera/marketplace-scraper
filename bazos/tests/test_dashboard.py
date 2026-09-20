"""Tests for the admin index dashboard (`bazos/dashboard.py`).

The panels are judgement calls, so what is worth asserting is not their wording but the
three things that would make them lie: a stalled cluster reading as healthy, a day with no
activity drawing as a gap instead of a zero, and the page growing a query per row.
"""
import re
from datetime import timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from django_q.models import Task

from bazos.dashboard import CHART_DAYS, dashboard_callback
from bazos.models import AdStatus


def _task(func, *, minutes_ago, success=True, seconds=1):
    # `Task.id` is varchar(32) — django-q stores a uuid4 hex, which is exactly 32.
    started = timezone.now() - timedelta(minutes=minutes_ago)
    return Task.objects.create(
        id=uuid4().hex, name=f"{func}-{minutes_ago}", func=func,
        started=started, stopped=started + timedelta(seconds=seconds),
        success=success, attempt_count=1,
    )


@pytest.mark.django_db
def test_callback_reports_an_empty_installation_without_dying():
    """Nothing has ever run — every panel still has to render a number."""
    context = dashboard_callback(None, {})

    assert context["queue"]["day"] == 0
    assert context["queue"]["last_minutes"] is None
    assert context["queue"]["stalled"] is True       # never run is not healthy
    assert context["scraper"]["pass_rate"] is None   # no attempts, not "0%"
    assert context["discovery"]["outcomes"] == 0


@pytest.mark.django_db
def test_a_silent_cluster_reads_as_stalled():
    """The heartbeat is hourly, so quiet for longer than that means dead, not idle."""
    _task("bazos.jobs.heartbeat", minutes_ago=20)
    assert dashboard_callback(None, {})["queue"]["stalled"] is False

    Task.objects.all().delete()
    _task("bazos.jobs.heartbeat", minutes_ago=200)
    assert dashboard_callback(None, {})["queue"]["stalled"] is True


@pytest.mark.django_db
def test_failures_are_counted_over_the_week_not_the_day():
    _task("bazos.jobs.sweep_delisted", minutes_ago=60 * 24 * 3, success=False)

    queue = dashboard_callback(None, {})["queue"]

    assert queue["failed_week"] == 1
    assert queue["day"] == 0, "a three-day-old run is not a run today"


@pytest.mark.django_db
def test_half_the_attempts_blocked_is_not_flagged_but_a_shutout_is(query):
    """~48% of Tor exits are 403'd by Bazos, so only zero successes is news."""
    from bazos.models import QueryRun

    now = timezone.now()
    for i in range(4):
        QueryRun.objects.create(query=query, run_start=now, run_end=now, success=(i % 2 == 0))

    healthy = dashboard_callback(None, {})["scraper"]
    assert healthy["pass_rate"] == 50
    assert healthy["blocked_out"] is False

    QueryRun.objects.update(success=False)
    assert dashboard_callback(None, {})["scraper"]["blocked_out"] is True


@pytest.mark.django_db
def test_pipeline_panel_separates_the_two_backlogs(query, make_ad, make_delivery):
    """PENDING is the filter's queue, APPROVED the sender's — a stuck stage is one or the other."""
    for i, status in enumerate([AdStatus.PENDING, AdStatus.PENDING, AdStatus.APPROVED, AdStatus.SENT]):
        ad = make_ad(query, bazos_id=500 + i)
        ad.save()
        make_delivery(ad, query, status=status)

    pipeline = dashboard_callback(None, {})["pipeline"]

    assert pipeline["pending"] == 2
    assert pipeline["approved"] == 1
    assert pipeline["sent"] == 1


@pytest.mark.django_db
def test_chart_series_is_dense(query, make_ad):
    """A day with no ads must be a zero. Chart.js joins across missing labels, so a sparse
    series would draw a line implying activity on days when nothing happened."""
    import json

    ad = make_ad(query, bazos_id=600)
    ad.save()

    chart = json.loads(dashboard_callback(None, {})["ads_chart"])

    assert len(chart["labels"]) == CHART_DAYS
    assert len(chart["datasets"][0]["data"]) == CHART_DAYS
    assert chart["datasets"][0]["data"][-1] == 1, "today's ad lands on the last bar"
    assert sum(chart["datasets"][0]["data"]) == 1


@pytest.mark.django_db
def test_index_page_renders_the_dashboard(client, query, make_ad, make_delivery):
    user = get_user_model().objects.create_superuser(
        username="dash2", email="dash2@test.local", password="password"
    )
    client.force_login(user)
    ad = make_ad(query, bazos_id=700)
    ad.save()
    make_delivery(ad, query, status=AdStatus.PENDING)
    _task("bazos.jobs.heartbeat", minutes_ago=5)

    response = client.get(reverse("admin:index"))
    content = response.content.decode()

    assert response.status_code == 200
    assert "Delivery backlog" in content
    assert "New ads per day" in content
    assert 'data-type="bar"' in content, "the chart component did not render"


@pytest.mark.django_db
def test_dashboard_cost_does_not_grow_with_the_table(django_assert_max_num_queries, query, make_ad, make_delivery):
    """Aggregates, not a query per row — this runs on every /admin/ load, on a Pi."""
    for i in range(25):
        ad = make_ad(query, bazos_id=800 + i)
        ad.save()
        make_delivery(ad, query, status=AdStatus.PENDING)
        _task("bazos.jobs.heartbeat", minutes_ago=i + 1)

    # 14 aggregates: eight for the operational panels, six for marketplace health. The
    # number is what matters less than its shape — it is constant in the size of every
    # table it reads, which is the property this test exists to keep.
    with django_assert_max_num_queries(14):
        dashboard_callback(None, {})


# ---------------------------------------------------------------------------
# Combined task history — Success and Failure are proxies over one table
# ---------------------------------------------------------------------------

@pytest.fixture
def task_admin_client(client, db):
    user = get_user_model().objects.create_superuser(
        username="tasks", email="tasks@test.local", password="password"
    )
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_task_history_interleaves_successes_and_failures(task_admin_client):
    """The question is "has this job been failing lately", which needs both in time order."""
    _task("bazos.jobs.sweep_delisted", minutes_ago=30, success=True)
    _task("bazos.jobs.sweep_delisted", minutes_ago=20, success=False)
    _task("bazos.jobs.heartbeat", minutes_ago=10, success=True)

    response = task_admin_client.get(reverse("admin:django_q_task_changelist"))

    assert response.status_code == 200
    assert response.context["cl"].result_count == 3, "both outcomes, one list"


@pytest.mark.django_db
def test_task_history_filters_by_job_and_by_outcome(task_admin_client):
    _task("bazos.jobs.sweep_delisted", minutes_ago=30, success=True)
    _task("bazos.jobs.sweep_delisted", minutes_ago=20, success=False)
    _task("bazos.jobs.heartbeat", minutes_ago=10, success=True)

    url = reverse("admin:django_q_task_changelist")
    by_job = task_admin_client.get(url, {"job_func": "bazos.jobs.sweep_delisted"})
    failures = task_admin_client.get(url, {"success__exact": "0"})

    assert by_job.context["cl"].result_count == 2
    assert failures.context["cl"].result_count == 1


@pytest.mark.django_db
def test_job_filter_labels_come_from_the_catalog(task_admin_client):
    """`bazos.jobs.sweep_delisted` should read as the Run-a-job page names it."""
    from django.contrib.admin.sites import AdminSite
    from django_q.models import Task as TaskModel

    from bazos.admin import JobFuncFilter, ThemedTaskHistoryAdmin
    from bazos.jobs import JOB_CATALOG

    _task("bazos.jobs.sweep_delisted", minutes_ago=5)
    model_admin = ThemedTaskHistoryAdmin(TaskModel, AdminSite())
    lookups = dict(JobFuncFilter(None, {}, TaskModel, model_admin).lookups(None, model_admin))

    assert lookups["bazos.jobs.sweep_delisted"] == JOB_CATALOG["bazos.jobs.sweep_delisted"].label


@pytest.mark.django_db
def test_duration_is_sortable(task_admin_client):
    """`Task.time_taken()` is a method, so django-q's own column cannot be ordered by it."""
    _task("bazos.jobs.heartbeat", minutes_ago=30, seconds=2)
    _task("bazos.jobs.sweep_delisted", minutes_ago=20, seconds=900)

    response = task_admin_client.get(reverse("admin:django_q_task_changelist"), {"o": "-4"})
    rows = list(response.context["cl"].result_list)

    assert response.status_code == 200
    assert rows[0].func == "bazos.jobs.sweep_delisted", "slowest first"


@pytest.mark.parametrize(
    "seconds,expected",
    [(0.4, "0.4s"), (3, "3.0s"), (12, "12s"), (90, "1m 30s"), (1009, "16m 49s")],
)
def test_durations_read_like_durations(seconds, expected):
    """Including sub-second: the heartbeat takes ~0.4s and "0s" reads like a broken column."""
    from bazos.dashboard import humanise_duration

    assert humanise_duration(timedelta(seconds=seconds)) == expected


# ---------------------------------------------------------------------------
# Marketplace health — each judged against its own history, not a shared number
# ---------------------------------------------------------------------------

def _runs(query, *, n, ok, error="MarketplaceBlockedError: blocked", when=None, days_ago=0):
    """`n` attempts of which `ok` succeeded, on one day."""
    from bazos.models import QueryRun

    start = (when or timezone.now()) - timedelta(days=days_ago)
    for i in range(n):
        QueryRun.objects.create(
            query=query, run_start=start, run_end=start,
            success=i < ok, error="" if i < ok else error,
        )


def _market(context, label):
    return next(m for m in context["markets"] if m["label"] == label)


@pytest.mark.django_db
def test_a_blocked_marketplace_at_its_usual_rate_is_not_flagged(query):
    """Bazos failed 56% of attempts in the week this was written and was perfectly fine."""
    for day in range(1, 8):
        _runs(query, n=20, ok=9, days_ago=day)
    _runs(query, n=20, ok=9)

    card = _market(dashboard_callback(None, {}), "Bazos")

    assert card["state"] == "ok"
    assert card["rate"] == 55
    assert card["baseline"] == 55


@pytest.mark.django_db
def test_a_marketplace_failing_far_more_than_usual_is_flagged(query):
    for day in range(1, 8):
        _runs(query, n=20, ok=18, days_ago=day)   # usually 10% failures
    _runs(query, n=20, ok=2)                      # today 90%

    card = _market(dashboard_callback(None, {}), "Bazos")

    assert card["state"] == "elevated"
    assert card["baseline"] == 10


@pytest.mark.django_db
def test_nothing_getting_through_beats_any_rate(query):
    _runs(query, n=12, ok=0)

    assert _market(dashboard_callback(None, {}), "Bazos")["state"] == "down"


@pytest.mark.django_db
def test_an_enabled_marketplace_that_tried_nothing_is_silent(query):
    """Worse than failing: the runner never even reached it."""
    assert query.enabled
    assert _market(dashboard_callback(None, {}), "Bazos")["state"] == "silent"


@pytest.mark.django_db
def test_non_block_failures_are_separated_from_blocks(query):
    """One RuntimeError has to stay visible beside three thousand blocks."""
    import json

    _runs(query, n=30, ok=0)
    _runs(query, n=2, ok=0, error="RuntimeError: endpoint 404")

    context = dashboard_callback(None, {})
    chart = json.loads(context["failures_chart"])

    assert chart["datasets"][0]["label"] == "Blocked (expected)"
    assert chart["datasets"][0]["data"][-1] == 30
    assert chart["datasets"][1]["data"][-1] == 2
    assert context["other_failures"] == [
        {"marketplace": "bazos", "error": "RuntimeError", "n": 2}
    ], "blocks must not appear in the contract-break table"


@pytest.mark.django_db
def test_stalled_queries_lists_only_enabled_ones_that_never_succeeded(query, category):
    from bazos.models import Query

    disabled = Query.objects.create(text="off", category=category, enabled=False,
                                    price_lower=0, price_upper=0, new_query=False)
    _runs(query, n=5, ok=0)
    _runs(disabled, n=5, ok=0)

    stalled = dashboard_callback(None, {})["stalled_queries"]

    assert [row["text"] for row in stalled] == [query.text]


@pytest.mark.django_db
def test_a_query_that_eventually_got_through_is_not_stalled(query):
    """The retry loop is the point: 4 blocks and a success is a healthy pass."""
    _runs(query, n=5, ok=1)

    assert dashboard_callback(None, {})["stalled_queries"] == []


# ---------------------------------------------------------------------------
# Two failure modes of the template itself, both invisible without rendering
# ---------------------------------------------------------------------------

DASHBOARD_TEMPLATE = Path(settings.BASE_DIR) / "templates" / "admin" / "index.html"


def test_every_colour_class_exists_in_unfolds_compiled_css():
    """Unfold ships a *precompiled* Tailwind build, so an unknown utility is a silent no-op.

    `text-orange-500` looked right, passed review and did nothing: the bundle carries
    `orange-700` and `dark:orange-400`. Nothing fails, the element just renders unstyled —
    which for a colour that means "this marketplace is unhealthy" is the worst way to be
    wrong.
    """
    import unfold

    css = (Path(unfold.__file__).parent / "static" / "unfold" / "css" / "styles.css").read_text()
    used = set(re.findall(r"(?:dark:)?text-(?:red|orange|green|blue|yellow|amber)-\d00",
                          DASHBOARD_TEMPLATE.read_text()))
    missing = [c for c in used if c.replace(":", "\\:") not in css]

    assert used, "no colour utilities found — did the template move?"
    assert not missing, f"not in unfold's compiled CSS, so these do nothing: {sorted(missing)}"


@pytest.mark.django_db
def test_template_comments_do_not_reach_the_page(client):
    """`{# ... #}` is single-line only; spanning lines makes Django emit it as text."""
    user = get_user_model().objects.create_superuser(
        username="dash3", email="dash3@test.local", password="password"
    )
    client.force_login(user)

    content = client.get(reverse("admin:index")).content.decode()

    assert "{#" not in content and "#}" not in content
    assert "Row 3" not in content, "a multi-line {# #} comment leaked into the page"
