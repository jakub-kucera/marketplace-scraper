"""Tests for the admin index dashboard (`bazos/dashboard.py`).

The panels are judgement calls, so what is worth asserting is not their wording but the
three things that would make them lie: a stalled cluster reading as healthy, a day with no
activity drawing as a gap instead of a zero, and the page growing a query per row.
"""
from datetime import timedelta
from uuid import uuid4

import pytest
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

    with django_assert_max_num_queries(10):
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
