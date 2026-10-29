"""Tests for the admin's "Run a job" page.

Its entire reason to exist is that django-q2's own Schedule admin will enqueue anything
without checking it: a mistyped dotted path or a wrong id becomes a `Failure` row in a
worker, ten seconds later and somewhere else. So the tests that matter are the ones proving
a bad argument is caught **before** anything reaches the queue.
"""
from unittest.mock import patch

import pytest
from django.urls import reverse_lazy

from marketplace.admin_jobs import RunJobForm
from marketplace.jobs import (
    AD_PK,
    DETECT_REPOSTS,
    FETCH_SELLER_RATINGS,
    GEOCODE_POSTAL_CODE,
    HEARTBEAT,
    JOB_CATALOG,
    SCORE_AD,
)
from marketplace.models import Ad, EmailPublisher, Marketplace

#: Reversed rather than hardcoded — this is the same name the sidebar entry uses, so a
#: rename of the admin method breaks both here and there rather than only in production.
RUN_JOB_URL = reverse_lazy("admin:django_q_schedule_run_a_job")


@pytest.fixture
def ad(db):
    return Ad.objects.create(
        external_id=7777, marketplace=Marketplace.BAZOS, url="https://x.test/1",
        name="MacBook", price_raw="1 Kč", price=1, location="Praha, 110 00",
        short_description="", publisher_name="",
    )


@pytest.fixture
def seller(db):
    return EmailPublisher.objects.create(bazos_id=4242)


def submit(data):
    form = RunJobForm(data)
    return form, form.is_valid()


# ---------------------------------------------------------------------------
# The catalog
# ---------------------------------------------------------------------------

def test_every_catalogued_path_is_a_real_task():
    """The point of choosing from a registry rather than typing a path: it cannot be
    mistyped. That only holds if the registry itself is right."""
    from importlib import import_module

    for func in JOB_CATALOG:
        module_path, _, attribute = func.rpartition(".")
        assert callable(getattr(import_module(module_path), attribute)), func


def test_other_apps_contribute_their_own_jobs():
    """`llm` and `refprice` register at `AppConfig.ready()` — `bazos` imports neither."""
    assert "llm.jobs.extract_ad_specs" in JOB_CATALOG
    assert "refprice.jobs.lookup_reference_price" in JOB_CATALOG


def test_every_argument_kind_the_catalog_uses_can_be_resolved():
    """A spec declaring a kind the form cannot read would only fail when someone picked it."""
    readable = {"", AD_PK, "postal_code", "publisher"}
    unknown = {s.arg for s in JOB_CATALOG.values()} - readable
    assert not unknown


# ---------------------------------------------------------------------------
# Validation — before anything is queued
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_a_valid_ad_id_resolves(ad):
    form, valid = submit({"job": SCORE_AD, "argument": str(ad.pk)})
    assert valid, form.errors
    assert form.cleaned_data["task_args"] == (ad.pk,)


@pytest.mark.django_db
def test_an_ad_that_does_not_exist_is_rejected(ad):
    _, valid = submit({"job": SCORE_AD, "argument": str(ad.pk + 10_000)})
    assert not valid


@pytest.mark.django_db
def test_a_non_numeric_ad_id_is_rejected(ad):
    _, valid = submit({"job": SCORE_AD, "argument": "the macbook one"})
    assert not valid


@pytest.mark.django_db
def test_a_job_that_takes_no_argument_rejects_one(db):
    """Not ignored silently: someone who typed an id meant it to be used, and a job that
    discarded it would look like it had run on the wrong thing."""
    _, valid = submit({"job": HEARTBEAT, "argument": "42"})
    assert not valid


@pytest.mark.django_db
def test_a_job_that_needs_an_argument_rejects_a_blank(db):
    _, valid = submit({"job": SCORE_AD, "argument": ""})
    assert not valid


@pytest.mark.django_db
def test_a_postal_code_is_normalised_not_just_accepted(db):
    form, valid = submit({"job": GEOCODE_POSTAL_CODE, "argument": "602 00"})
    assert valid, form.errors
    assert form.cleaned_data["task_args"] == ("60200",)


@pytest.mark.django_db
def test_an_unusable_postal_code_is_rejected(db):
    _, valid = submit({"job": GEOCODE_POSTAL_CODE, "argument": "Brno"})
    assert not valid


@pytest.mark.django_db
def test_a_seller_needs_its_kind_as_well_as_its_number(seller):
    """A seller is a *pair* of ids across two tables, so the number alone is ambiguous."""
    _, valid = submit({"job": FETCH_SELLER_RATINGS, "argument": str(seller.pk)})
    assert not valid

    form, valid = submit({"job": FETCH_SELLER_RATINGS, "argument": f"email:{seller.pk}"})
    assert valid, form.errors
    assert form.cleaned_data["task_args"] == ("email", seller.pk)


@pytest.mark.django_db
def test_a_seller_in_the_other_table_is_rejected(seller):
    """`seller` is an EmailPublisher; asking for it as a phone id must not silently work."""
    _, valid = submit({"job": DETECT_REPOSTS, "argument": f"phone:{seller.pk}"})
    assert not valid


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_the_page_renders_for_staff(admin_client):
    response = admin_client.get(RUN_JOB_URL)

    assert response.status_code == 200
    assert b"Run a job" in response.content


@pytest.mark.django_db
def test_posting_a_valid_job_enqueues_exactly_one_task(admin_client, ad):
    with patch("marketplace.admin_jobs.async_task", return_value="task-id") as async_task:
        response = admin_client.post(
            RUN_JOB_URL, {"job": SCORE_AD, "argument": str(ad.pk)}, follow=True
        )

    async_task.assert_called_once_with(SCORE_AD, ad.pk)
    assert b"Queued" in response.content


@pytest.mark.django_db
def test_an_invalid_argument_queues_nothing(admin_client, ad):
    """The property the whole page exists for."""
    with patch("marketplace.admin_jobs.async_task") as async_task:
        response = admin_client.post(
            RUN_JOB_URL, {"job": SCORE_AD, "argument": str(ad.pk + 10_000)}
        )

    async_task.assert_not_called()
    assert response.status_code == 200  # re-rendered with the error, not redirected


@pytest.mark.django_db
def test_an_anonymous_visitor_is_sent_to_the_login_page(client):
    """Unfold's action decorator wraps the view in `admin_view`, so the check inside it is
    never reached through this URL. Asserted anyway — the page enqueues work."""
    response = client.get(RUN_JOB_URL)

    assert response.status_code == 302
    assert "/admin/login/" in response.url


@pytest.mark.django_db
def test_a_direct_call_by_a_non_staff_user_is_a_403_not_a_500():
    """The in-view check, for a caller that bypasses `admin_view` — `PermissionDenied`
    rather than `PermissionError`, because only the former renders as 403."""
    from django.contrib.auth.models import AnonymousUser
    from django.core.exceptions import PermissionDenied
    from django.test import RequestFactory

    from marketplace.admin_jobs import run_job_view

    request = RequestFactory().get(RUN_JOB_URL)
    request.user = AnonymousUser()

    with pytest.raises(PermissionDenied):
        run_job_view(request)


def test_the_sidebar_entry_points_at_the_page():
    """The sidebar is hand-maintained, so a link there is not checked by anything else —
    and this one is reversed from Unfold's generated action name, which a rename would
    silently invalidate."""
    from django.conf import settings

    # `settings.UNFOLD` is typed as a plain mapping, so its nested values arrive as `object`.
    navigation: list = settings.UNFOLD["SIDEBAR"]["navigation"]  # type: ignore[index]
    links = [
        item["link"]
        for group in navigation
        for item in group["items"]
        if item["title"] == "Run a job"
    ]
    assert links and str(links[0]) == str(RUN_JOB_URL)
