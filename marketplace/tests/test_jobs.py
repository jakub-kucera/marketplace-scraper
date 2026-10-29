"""Tests for the django-q2 task layer and its schedules.

The risks here are not in the library, so these do not test django-q2. They test the two
things that are ours and that fail *silently*:

- a schedule pointing at a dotted path that no longer imports (a rename looks like a
  refactor and stops the job forever, with no error anywhere), and
- `ensure_schedules` clobbering a cadence someone edited in the admin, which would make the
  admin control a lie.
"""
import ast
from importlib import import_module
from io import StringIO
from types import SimpleNamespace
from typing import cast
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone
from django_q.models import Schedule

from marketplace.scraping.session import AllCircuitsBlocked

from marketplace.const import DELIST_MAX_CHUNK_ROUNDS, JOB_BLOCK_MAX_DEFERRALS
from marketplace.jobs import (
    COMPARE_BAZOS_SCRAPERS,
    DETECT_REPOSTS,
    FETCH_SELLER_LISTINGS,
    FETCH_FULL_DESCRIPTION,
    FETCH_SELLER_RATINGS,
    GEOCODE_POSTAL_CODE,
    REFRESH_AD,
    HEARTBEAT,
    PRUNE_QUERY_RUNS,
    PRUNE_STATUS_LOGS,
    RESCORE_ADS,
    SCHEDULES,
    SCORE_AD,
    SWEEP_DELISTED,
    SYNC_VINTED_CATALOGS,
    heartbeat,
)


def resolve(dotted: str):
    module_path, _, attribute = dotted.rpartition(".")
    return getattr(import_module(module_path), attribute)


# ---------------------------------------------------------------------------
# The dotted paths django-q2 persists
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "dotted",
    [
        SWEEP_DELISTED, HEARTBEAT, PRUNE_STATUS_LOGS, PRUNE_QUERY_RUNS,
        SCORE_AD, RESCORE_ADS, SYNC_VINTED_CATALOGS, COMPARE_BAZOS_SCRAPERS,
        GEOCODE_POSTAL_CODE, FETCH_FULL_DESCRIPTION, REFRESH_AD, FETCH_SELLER_RATINGS,
        FETCH_SELLER_LISTINGS, DETECT_REPOSTS,
    ],
)
def test_every_task_path_resolves(dotted):
    """django-q2 stores the path as a string, so a rename fails at *run* time, in a worker,
    as a Failure row nobody is watching. Resolve them here instead."""
    assert callable(resolve(dotted))


def test_every_scheduled_path_resolves():
    for name, spec in SCHEDULES.items():
        assert callable(resolve(spec.func)), f"schedule {name} points at an unimportable path"


# ---------------------------------------------------------------------------
# ensure_schedules
# ---------------------------------------------------------------------------

def run_ensure():
    out = StringIO()
    call_command("ensure_schedules", stdout=out)
    return out.getvalue()


@pytest.mark.django_db
def test_creates_every_schedule():
    report = run_ensure()

    assert Schedule.objects.count() == len(SCHEDULES)
    for name in SCHEDULES:
        assert Schedule.objects.filter(name=name).exists()
        assert name in report


@pytest.mark.django_db
def test_is_idempotent():
    run_ensure()
    first = list(Schedule.objects.values_list("pk", flat=True))

    run_ensure()

    assert list(Schedule.objects.values_list("pk", flat=True)) == first


@pytest.mark.django_db
def test_does_not_overwrite_a_cadence_edited_in_the_admin():
    """Editing cadence in the admin is the whole reason for the queue; a deploy silently
    reverting that edit would make the page a control that does nothing."""
    run_ensure()
    schedule = Schedule.objects.get(name="cluster-heartbeat")
    schedule.minutes = 5
    schedule.save()

    run_ensure()

    schedule.refresh_from_db()
    assert schedule.minutes == 5


@pytest.mark.django_db
def test_repoints_a_schedule_whose_task_was_renamed():
    """The dotted path is ours to own — a stale one fails silently in a worker."""
    run_ensure()
    Schedule.objects.filter(name="delisting-sweep").update(func="marketplace.jobs.gone_away")

    report = run_ensure()

    assert Schedule.objects.get(name="delisting-sweep").func == SWEEP_DELISTED
    assert "repointed" in report


@pytest.mark.django_db
def test_schedules_repeat_forever():
    """`repeats=-1`. A schedule that counts down to zero stops without ever erroring."""
    run_ensure()

    assert set(Schedule.objects.values_list("repeats", flat=True)) == {-1}


# ---------------------------------------------------------------------------
# The tasks themselves
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_heartbeat_returns_a_recorded_summary():
    """django-q2 stores the return value on the Success row, which is what makes the admin
    a run log — so a task that returns nothing is a blank row."""
    assert "alive at" in heartbeat()


@pytest.mark.django_db
def test_sweep_returns_the_command_summary(make_ad, query):
    from marketplace.jobs import sweep_delisted

    result = sweep_delisted(limit=0)

    assert "due" in result


@pytest.mark.django_db
def test_prune_tasks_return_what_they_deleted():
    """A blank Success row is a run log that does not log anything."""
    from marketplace.jobs import prune_query_runs, prune_status_logs

    assert "deleted" in prune_status_logs()
    assert "query runs" in prune_query_runs()


@pytest.mark.django_db
def test_a_failing_task_raises_rather_than_returning_quietly(monkeypatch):
    """A swallowed exception becomes a green Success row, which is the one thing a run log
    must never do."""
    from marketplace import jobs

    def boom(*args, **kwargs):
        raise RuntimeError("sweep exploded")

    monkeypatch.setattr(jobs, "call_command", boom)

    with pytest.raises(RuntimeError):
        jobs.sweep_delisted()


# ---------------------------------------------------------------------------
# Cluster configuration — the constraint that is not a tuning choice
# ---------------------------------------------------------------------------

def test_the_cluster_runs_exactly_one_worker():
    """JOB_QUEUE.md §2: the shared requests.Session and its Tor circuit are not safe for
    concurrent callers. Raising this needs the `requires_bazos_session` lock first, so it is
    pinned here rather than left to whoever next tunes throughput."""
    from django.conf import settings

    assert settings.Q_CLUSTER["workers"] == 1


def test_retry_exceeds_timeout():
    """Otherwise django-q2 re-queues a task that is still running, underneath itself."""
    from django.conf import settings

    # `settings.Q_CLUSTER` is typed as a plain mapping, so the values arrive as `object`.
    retry = cast(int, settings.Q_CLUSTER["retry"])
    timeout = cast(int, settings.Q_CLUSTER["timeout"])

    assert retry > timeout


def test_missed_schedules_do_not_replay():
    """catch_up=False: a schedule missed during downtime fires once on return and skips to
    the next future slot, rather than replaying every occurrence it slept through."""
    from django.conf import settings

    assert settings.Q_CLUSTER["catch_up"] is False


# ---------------------------------------------------------------------------
# The chunked sweep — the prerequisite for every interactive job
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_an_explicit_limit_runs_once_and_never_re_enqueues(monkeypatch):
    """`limit` given is the one-off: do exactly that much and stop."""
    from marketplace import jobs

    queued = []
    monkeypatch.setattr("django_q.tasks.async_task", lambda *a, **kw: queued.append((a, kw)))

    jobs.sweep_delisted(limit=5)

    assert queued == []


@pytest.mark.django_db
def test_a_chunk_that_leaves_work_queues_the_next_one(monkeypatch, make_ad):
    from marketplace import jobs

    queued = []
    monkeypatch.setattr("django_q.tasks.async_task", lambda *a, **kw: queued.append((a, kw)))
    # 3 due before the chunk, 1 after: progress was made and work remains.
    counts = iter([3, 1])
    monkeypatch.setattr(jobs, "call_command", lambda *a, **kw: None)
    monkeypatch.setattr(
        "marketplace.delisting.due_for_check",
        lambda *a, **kw: _CountOnly(next(counts)),
    )

    result = jobs.sweep_delisted()

    assert len(queued) == 1
    assert queued[0][1]["rounds_left"] == DELIST_MAX_CHUNK_ROUNDS - 1
    assert "next chunk queued" in result


@pytest.mark.django_db
def test_a_chunk_that_clears_nothing_stops_instead_of_looping(monkeypatch):
    """The stop that matters. A chunk whose every batch was blocked leaves its ads due, so
    without this the job re-queues itself against a marketplace that is refusing us — a loop
    that looks like progress."""
    from marketplace import jobs

    queued = []
    monkeypatch.setattr("django_q.tasks.async_task", lambda *a, **kw: queued.append((a, kw)))
    counts = iter([3, 3])
    monkeypatch.setattr(jobs, "call_command", lambda *a, **kw: None)
    monkeypatch.setattr(
        "marketplace.delisting.due_for_check", lambda *a, **kw: _CountOnly(next(counts))
    )

    result = jobs.sweep_delisted()

    assert queued == []
    assert "made no progress" in result


@pytest.mark.django_db
def test_the_round_budget_is_a_backstop_for_slow_progress(monkeypatch):
    """Separate from the no-progress stop: this covers a sweep that clears *some* ads every
    round but never finishes."""
    from marketplace import jobs

    queued = []
    monkeypatch.setattr("django_q.tasks.async_task", lambda *a, **kw: queued.append((a, kw)))
    counts = iter([3, 2])
    monkeypatch.setattr(jobs, "call_command", lambda *a, **kw: None)
    monkeypatch.setattr(
        "marketplace.delisting.due_for_check", lambda *a, **kw: _CountOnly(next(counts))
    )

    result = jobs.sweep_delisted(rounds_left=1)

    assert queued == []
    assert "round budget spent" in result


class _CountOnly:
    """`due_for_check()` returns a QuerySet; the chunk logic only ever counts it."""

    def __init__(self, count: int):
        self._count = count

    def count(self) -> int:
        return self._count


# ---------------------------------------------------------------------------
# Price scoring
# ---------------------------------------------------------------------------

@pytest.fixture
def saved_ad(db):
    """`make_ad` returns an *unsaved* Ad and takes a query it no longer stores; these tasks
    take a pk, so they need a row."""
    from marketplace.models import Ad, Marketplace

    def _factory(external_id=901):
        return Ad.objects.create(
            external_id=external_id, marketplace=Marketplace.BAZOS,
            url=f"https://pc.bazos.cz/inzerat/{external_id}/test.php",
            name="MacBook Pro 14 M1", price_raw="31 000 Kč", price=31000,
            location="Praha, 110 00", short_description="", publisher_name="Seller",
        )
    return _factory


@pytest.mark.django_db
def test_score_ad_reports_no_model_separately_from_a_decline(saved_ad):
    """Three outcomes, not two. "No registered model claims this ad" and "a model looked
    and had no opinion" are different facts, and only one of them is worth revisiting."""
    from marketplace import jobs

    ad = saved_ad()

    with patch("marketplace.pricing.scoring.score_ad", return_value=None):
        assert "no model claims it" in jobs.score_ad(ad.pk)

    declined = SimpleNamespace(
        declined_reason="damage words", model_name="macbook", predicted=None, discount_pct=None
    )
    with patch("marketplace.pricing.scoring.score_ad", return_value=declined):
        assert "declined" in jobs.score_ad(ad.pk)

    scored = SimpleNamespace(
        declined_reason=None, model_name="macbook", predicted=31000, discount_pct=-12.0
    )
    with patch("marketplace.pricing.scoring.score_ad", return_value=scored):
        assert "31000" in jobs.score_ad(ad.pk)


@pytest.mark.django_db
def test_score_ad_forces_a_refresh(saved_ad):
    """The freshness check keys on the ARTIFACT version, so a row written by older code
    short-circuits and comes back unchanged. The only reason to ask for one ad by hand is
    that the stored answer is suspect."""
    from marketplace import jobs

    ad = saved_ad()
    with patch("marketplace.pricing.scoring.score_ad", return_value=None) as predict:
        jobs.score_ad(ad.pk)

    assert predict.call_args.kwargs["refresh"] is True


@pytest.mark.django_db
def test_rescore_omits_model_when_not_given():
    """`--model` defaults to None in the command; passing it explicitly is harmless, but
    passing a *different* falsy value would silently narrow the backfill to nothing."""
    from marketplace import jobs

    with patch.object(jobs, "call_command") as call:
        jobs.rescore_ads()

    assert "model" not in call.call_args.kwargs
    assert call.call_args.kwargs["missing_features"] is False


@pytest.mark.django_db
def test_the_admin_action_queues_one_task_per_ad(saved_ad, monkeypatch):
    from django.contrib import admin as dj_admin
    from django.contrib.messages import INFO
    from django.test import RequestFactory

    from marketplace.jobs import SCORE_AD
    from marketplace.models import Ad

    first, second = saved_ad(901), saved_ad(902)
    model_admin = dj_admin.site._registry[Ad]
    captured: list[tuple[int, str]] = []
    monkeypatch.setattr(
        model_admin, "message_user",
        lambda req, msg, level=INFO, **kw: captured.append((level, msg)),
    )

    with patch("marketplace.admin.async_task") as async_task, \
         patch("marketplace.pricing.scoring.score_ad") as predict:
        model_admin.score_selected_ads(
            RequestFactory().post("/admin/bazos/ad/"),
            Ad.objects.filter(pk__in=[first.pk, second.pk]),
        )

    assert {call.args for call in async_task.call_args_list} == {
        (SCORE_AD, first.pk), (SCORE_AD, second.pk)
    }
    predict.assert_not_called()
    assert "Queued 2" in captured[0][1]


@pytest.mark.django_db
def test_vinted_catalog_sync_wraps_the_command():
    """The report is the point: `catalog_ids` live in a JSONField and are not an FK, so a
    retired node fails as an empty result rather than as an error."""
    from marketplace import jobs

    with patch.object(jobs, "call_command") as call:
        jobs.sync_vinted_catalogs()

    assert call.call_args.args[0] == "create_vinted_catalogs"


@pytest.mark.django_db
def test_scraper_parity_check_wraps_the_command():
    """The standing drift check for P21a's cutover: `BazosApiScraper` is registered but no
    Query selects it, so nothing would notice if it stopped agreeing with the HTML scraper."""
    from marketplace import jobs

    with patch.object(jobs, "call_command") as call:
        jobs.compare_bazos_scrapers(limit=3)

    assert call.call_args.args[0] == "compare_bazos_scrapers"
    assert call.call_args.kwargs["limit"] == 3


@pytest.mark.django_db
def test_parity_check_omits_limit_when_not_given():
    """`--limit` defaults to 5 in the command; passing None would override that with None."""
    from marketplace import jobs

    with patch.object(jobs, "call_command") as call:
        jobs.compare_bazos_scrapers()

    assert "limit" not in call.call_args.kwargs


# ---------------------------------------------------------------------------
# Geocoding one code on demand
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_an_already_cached_code_makes_no_request():
    """The common case when the action runs over a selection. A no-op that says so beats
    one that looks like a lookup."""
    from marketplace import jobs
    from marketplace.models import PostalCode

    PostalCode.objects.create(code="11000", city="Praha 1", latitude=50.08, longitude=14.42)

    with patch("marketplace.geo.geocode_postal_code") as geocode:
        result = jobs.geocode_postal_code("110 00")

    geocode.assert_not_called()
    assert "already cached" in result


@pytest.mark.django_db
def test_an_unparseable_code_is_reported_not_raised():
    """A code the parser cannot read is a data problem to report, not a transport failure to
    retry — and a Failure row would say the wrong thing about it."""
    from marketplace import jobs

    with patch("marketplace.geo.geocode_postal_code") as geocode:
        result = jobs.geocode_postal_code("not a code")

    geocode.assert_not_called()
    assert "not a usable postal code" in result


@pytest.mark.django_db
def test_zip_php_not_knowing_a_code_is_distinct_from_being_blocked():
    """`None` from the geocoder is a real answer about the code. Being blocked raises, so
    the run log can tell "there is no such place" from "we could not ask"."""
    from marketplace import jobs

    with patch("marketplace.geo.geocode_postal_code", return_value=None), \
         patch("marketplace.scraping.session.build_ip_changer"), \
         patch("marketplace.scraping.session.with_rotation", side_effect=lambda c, op, **kw: op(None)):
        result = jobs.geocode_postal_code("99999")

    assert "unresolved" in result


@pytest.mark.django_db
def test_the_query_action_skips_queries_with_no_centre(query, monkeypatch):
    from django.contrib import admin as dj_admin
    from django.contrib.messages import INFO
    from django.test import RequestFactory

    from marketplace.jobs import GEOCODE_POSTAL_CODE
    from marketplace.models import Query

    query.filter_location_center = "11000"
    query.save()
    model_admin = dj_admin.site._registry[Query]
    captured: list[tuple[int, str]] = []
    monkeypatch.setattr(
        model_admin, "message_user",
        lambda req, msg, level=INFO, **kw: captured.append((level, msg)),
    )

    with patch("marketplace.admin.async_task") as async_task:
        model_admin.geocode_filter_centres(
            RequestFactory().post("/admin/bazos/query/"), Query.objects.all()
        )

    assert [call.args for call in async_task.call_args_list] == [(GEOCODE_POSTAL_CODE, "11000")]
    assert "Queued 1" in captured[0][1]


@pytest.mark.django_db
def test_an_empty_detail_fetch_is_reported_not_raised(saved_ad):
    """A 410 on the API path, or a detail page carrying nothing. The request worked and the
    answer was "nothing here", so a Failure row would misdescribe it."""
    from marketplace import jobs

    ad = saved_ad()
    with patch("marketplace.enrichment.fetch_full_description", side_effect=lambda a, s: a), \
         patch("marketplace.scraping.session.build_ip_changer"), \
         patch("marketplace.scraping.session.with_rotation", side_effect=lambda c, op, **kw: op(None)):
        result = jobs.fetch_full_description(ad.pk)

    assert "no description returned" in result


@pytest.mark.django_db
def test_an_unknown_publisher_kind_raises():
    """A seller is a *pair* of opaque ids, so the pk alone cannot say which table to read —
    a typo in the kind must fail loudly rather than pick one."""
    from marketplace import jobs

    with pytest.raises(ValueError):
        jobs.fetch_seller_ratings("carrier-pigeon", 1)


# ---------------------------------------------------------------------------
# The session-based wrappers
#
# Thin by design, but they were the least-covered code here and the only part a
# 2026-09-17 live run exercised before CI did. What they must get right: resolve the
# right row, hand `with_rotation` a session-taking callable, and report an outcome
# rather than a bare "done".
# ---------------------------------------------------------------------------

@pytest.fixture
def publishers(db):
    from marketplace.models import EmailPublisher, PhonePublisher

    return (
        EmailPublisher.objects.create(bazos_id=111),
        PhonePublisher.objects.create(bazos_id=222),
    )


def _straight_through(changer, operation, **kwargs):
    """Stand in for `with_rotation`, running the operation once against a dummy session."""
    return operation(MagicMock())


@pytest.mark.django_db
@pytest.mark.parametrize("kind,index,param", [("email", 0, "email_id"), ("phone", 1, "phone_id")])
def test_ratings_resolves_the_publisher_the_kind_names(publishers, kind, index, param):
    """A seller is a *pair* of ids in two tables, so the pk alone does not say which."""
    from marketplace import jobs

    publisher = publishers[index]
    with patch("marketplace.scraping.session.build_ip_changer"), \
         patch("marketplace.scraping.session.with_rotation", side_effect=_straight_through), \
         patch("marketplace.ratings.fetch_seller_ratings") as fetch:
        fetch.return_value = "2+ / 0- / 1~"
        out = jobs.fetch_seller_ratings(kind, publisher.pk)

    assert fetch.call_args.args[0].pk == publisher.pk
    assert fetch.call_args.args[0].ratings_param == param
    assert str(publisher.bazos_id) in out


@pytest.mark.django_db
def test_seller_listings_reports_what_was_created(publishers):
    from marketplace import jobs

    with patch("marketplace.scraping.session.build_ip_changer"), \
         patch("marketplace.scraping.session.with_rotation", side_effect=_straight_through), \
         patch("marketplace.enrichment.fetch_seller_listings", return_value="210 listed, 210 new, 0 already known"):
        out = jobs.fetch_seller_listings("email", publishers[0].pk)

    assert "210 new" in out


@pytest.mark.django_db
def test_refresh_ad_passes_the_enrichment_result_straight_through(saved_ad):
    from marketplace import jobs

    ad = saved_ad(910)
    with patch("marketplace.scraping.session.build_ip_changer"), \
         patch("marketplace.scraping.session.with_rotation", side_effect=_straight_through), \
         patch("marketplace.enrichment.refresh_ad", return_value=f"ad {ad.pk}: still listed"):
        assert jobs.refresh_ad(ad.pk) == f"ad {ad.pk}: still listed"


@pytest.mark.django_db
def test_a_successful_detail_fetch_reports_size_and_seller(saved_ad):
    from marketplace import jobs
    from marketplace.models import EmailPublisher

    ad = saved_ad(911)

    def fetched(a, session):
        a.full_description = "x" * 2346
        a.email_publisher = EmailPublisher.objects.create(bazos_id=333)
        return a

    with patch("marketplace.scraping.session.build_ip_changer"), \
         patch("marketplace.scraping.session.with_rotation", side_effect=_straight_through), \
         patch("marketplace.enrichment.fetch_full_description", side_effect=fetched):
        out = jobs.fetch_full_description(ad.pk)

    assert "2346 chars" in out and "seller resolved" in out


@pytest.mark.django_db
def test_detect_reposts_resolves_the_publisher_and_counts_links(publishers):
    from marketplace import jobs

    with patch("marketplace.reposts.detect_reposts", return_value=3) as detect:
        out = jobs.detect_reposts("phone", publishers[1].pk)

    assert detect.call_args.args[0].pk == publishers[1].pk
    assert "3 relist(s)" in out


# ---------------------------------------------------------------------------
# A blocked exit is backpressure, not a failed job
# ---------------------------------------------------------------------------

def _blocked(*_args, **_kwargs):
    raise AllCircuitsBlocked("Ratings for phone id 222: blocked on all 8 circuits")


@pytest.mark.django_db
def test_a_blocked_job_defers_itself_instead_of_dying(publishers, monkeypatch):
    """The whole point. `with_rotation` spends its eight rotations in about fifteen seconds,
    and the exits it draws are correlated by operator - the incident that prompted this had
    six of eight in two netblocks. More rotations in the same fifteen seconds is the wrong
    lever; the same request later, when Tor routes it differently, is the right one."""
    from marketplace import jobs
    _, phone = publishers
    monkeypatch.setattr("marketplace.scraping.session.with_rotation", _blocked)

    result = jobs.fetch_seller_ratings("phone", phone.pk)

    assert "blocked" in result and "retry" in result.lower()
    deferral = Schedule.objects.get()
    assert deferral.func == FETCH_SELLER_RATINGS
    assert deferral.schedule_type == Schedule.ONCE
    assert deferral.next_run > timezone.now()


@pytest.mark.django_db
def test_the_deferred_run_carries_its_arguments_and_its_place_in_the_chain(publishers, monkeypatch):
    """Args round-trip through a TextField and `ast.literal_eval`, which is the part most
    likely to break silently - a deferral that loses its publisher would retry nothing."""
    from marketplace import jobs
    _, phone = publishers
    monkeypatch.setattr("marketplace.scraping.session.with_rotation", _blocked)

    jobs.fetch_seller_ratings("phone", phone.pk)

    deferral = Schedule.objects.get()
    assert ast.literal_eval(deferral.args) == ("phone", phone.pk)
    assert ast.literal_eval(deferral.kwargs)["deferral"] == 1


@pytest.mark.django_db
def test_a_deferral_is_not_also_retried_by_the_cluster(publishers, monkeypatch):
    """`django_q/monitor.py:52` only acknowledges a task when it succeeded *or* carries
    `ack_failure`. Without this the cluster's own retry (`retry: 60*60`, `max_attempts: 3`)
    would re-run each give-up and start a fresh chain: three attempts x three deferrals is
    twelve runs and ninety-six blocked requests, and "gave up" would not be true."""
    from marketplace import jobs
    _, phone = publishers
    monkeypatch.setattr("marketplace.scraping.session.with_rotation", _blocked)

    jobs.fetch_seller_ratings("phone", phone.pk)

    assert ast.literal_eval(Schedule.objects.get().kwargs)["q_options"]["ack_failure"] is True


@pytest.mark.django_db
def test_the_deferral_cleans_itself_up_when_it_fires(publishers, monkeypatch):
    """`django_q/scheduler.py:130-137` deletes a fired ONCE schedule only when `repeats < 0`;
    with any other value it sets `repeats = 0` and saves, leaving a dead row. The field
    default is -1, so the fix is to not pass `repeats` at all - which looks like an omission
    and is why this is pinned."""
    from marketplace import jobs
    _, phone = publishers
    monkeypatch.setattr("marketplace.scraping.session.with_rotation", _blocked)

    jobs.fetch_seller_ratings("phone", phone.pk)

    assert Schedule.objects.get().repeats < 0


@pytest.mark.django_db
def test_the_last_deferral_gives_up_loudly_rather_than_starting_another(publishers, monkeypatch):
    """A re-enqueueing task that cannot finish is a loop that looks like progress - the
    failure mode `sweep_delisted`'s docstring warns about. It raises rather than returning a
    string because by this point the run carries `ack_failure`, so the Failure row is final
    and honest instead of being silently re-run."""
    from marketplace import jobs
    _, phone = publishers
    monkeypatch.setattr("marketplace.scraping.session.with_rotation", _blocked)

    with pytest.raises(AllCircuitsBlocked):
        jobs.fetch_seller_ratings("phone", phone.pk, deferral=JOB_BLOCK_MAX_DEFERRALS)

    assert Schedule.objects.count() == 0


@pytest.mark.django_db
def test_a_non_block_failure_is_still_a_failure(publishers, monkeypatch):
    """This changes behaviour for `AllCircuitsBlocked` and nothing else. Burying a real
    error behind a retry would be worse than the bug being fixed."""
    from marketplace import jobs
    _, phone = publishers

    def boom(*_a, **_kw):
        raise RuntimeError("no usable ratings response")

    monkeypatch.setattr("marketplace.scraping.session.with_rotation", boom)

    with pytest.raises(RuntimeError):
        jobs.fetch_seller_ratings("phone", phone.pk)

    assert Schedule.objects.count() == 0


@pytest.mark.django_db
def test_a_job_that_works_leaves_no_deferral_behind(publishers, monkeypatch):
    from marketplace import jobs
    from marketplace.ratings import RatingCounts

    email, _ = publishers
    monkeypatch.setattr("marketplace.scraping.session.with_rotation", lambda *a, **kw: RatingCounts(positive=2))

    result = jobs.fetch_seller_ratings("email", email.pk)

    assert "2+" in result
    assert Schedule.objects.count() == 0


@pytest.mark.django_db
@pytest.mark.parametrize("func,args", [
    ("fetch_seller_listings", ("phone",)),
    ("fetch_full_description", ()),
    ("refresh_ad", ()),
    ("geocode_postal_code", ()),
])
def test_every_job_that_touches_the_network_defers(func, args, publishers, saved_ad, monkeypatch):
    """Five jobs reach `with_rotation` and they share one failure mode; fixing the one that
    happened to fail first would leave the other four to bite the same way."""
    from marketplace import jobs
    _, phone = publishers
    monkeypatch.setattr("marketplace.scraping.session.with_rotation", _blocked)
    call_args = args + ((phone.pk,) if args else (saved_ad().pk,) if func != "geocode_postal_code" else ("11000",))

    result = getattr(jobs, func)(*call_args)

    assert "blocked" in result
    assert Schedule.objects.count() == 1
