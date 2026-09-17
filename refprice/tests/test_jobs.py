"""Tests for `refprice/jobs.py` and the admin action that feeds it.

Two things here are ours and fail silently: the dotted paths django-q2 persists in a
`Schedule` row, and an admin action that claims to have done work it only queued.
"""
from importlib import import_module
from unittest.mock import patch

import pytest
from django.contrib import admin as dj_admin
from django.contrib.messages import INFO

from bazos.models import Ad, Marketplace
from refprice.jobs import (
    LOOKUP_REFERENCE_PRICE,
    REFRESH_STALE_REFERENCE_PRICES,
    lookup_reference_price,
    refresh_stale_reference_prices,
)


def resolve(dotted: str):
    module_path, _, attribute = dotted.rpartition(".")
    return getattr(import_module(module_path), attribute)


@pytest.fixture
def ad(db):
    return Ad.objects.create(
        external_id=555, marketplace=Marketplace.BAZOS, url="https://example.test/1",
        name="Makita DHP484Z", price_raw="3 000 Kč", price=3000,
        location="Praha 1, 110 00", short_description="aku vrtacka",
    )


# ---------------------------------------------------------------------------
# The dotted paths
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dotted", [LOOKUP_REFERENCE_PRICE, REFRESH_STALE_REFERENCE_PRICES])
def test_every_task_path_resolves(dotted):
    """A rename looks like a refactor and stops the schedule forever, failing at run time in
    a worker as a Failure row nobody is watching."""
    assert callable(resolve(dotted))


@pytest.mark.django_db
def test_the_refresh_schedule_is_registered_from_this_app():
    """Registered at `AppConfig.ready()`, not declared in `bazos.jobs` — `bazos` imports
    nothing from `refprice`, and deleting this app must break nothing there."""
    from bazos.jobs import SCHEDULES

    assert "refresh-stale-reference-prices" in SCHEDULES
    assert SCHEDULES["refresh-stale-reference-prices"].func == REFRESH_STALE_REFERENCE_PRICES


def test_bazos_jobs_does_not_import_refprice():
    """The dependency points inward. `register_schedule` exists precisely so this stays true.

    Checks the import statements rather than the text: `refprice` is *named* in a comment
    there, explaining why the seam exists, and a substring search would make documenting the
    reason fail the test that enforces it.
    """
    import ast
    import pathlib

    source = pathlib.Path(__import__("bazos").__file__).parent / "jobs.py"
    imported: list[str] = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)

    assert not [name for name in imported if name.split(".")[0] == "refprice"]


# ---------------------------------------------------------------------------
# The tasks
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_lookup_takes_a_pk_and_reports_the_status(ad):
    """The status is the outcome — NO_MARKET ("it exists, nobody sells it") is information
    about the ad, not an absence of it, so a bare "done" would throw it away."""
    with patch("refprice.services.lookup_reference_price") as resolve_mock:
        resolve_mock.return_value.status = "NO_MATCH"
        result = lookup_reference_price(ad.pk)

    assert f"ad {ad.pk}" in result and "NO_MATCH" in result
    assert resolve_mock.call_args.kwargs["ad"].pk == ad.pk


@pytest.mark.django_db
def test_a_missing_ad_raises_rather_than_returning_quietly(ad):
    """django-q2 records the traceback on Failure. Swallowing this would be a green row for
    a task that did nothing."""
    with pytest.raises(Ad.DoesNotExist):
        lookup_reference_price(ad.pk + 10_000)


@pytest.mark.django_db
def test_refresh_stale_wraps_the_command():
    with patch("refprice.jobs.call_command") as call:
        result = refresh_stale_reference_prices(limit=3)

    assert call.call_args.kwargs["refresh_stale"] is True
    assert call.call_args.kwargs["limit"] == 3
    assert result


@pytest.mark.django_db
def test_refresh_stale_omits_limit_when_not_given():
    """`--limit` has a default in the command; passing None would override it with None."""
    with patch("refprice.jobs.call_command") as call:
        refresh_stale_reference_prices()

    assert "limit" not in call.call_args.kwargs


# ---------------------------------------------------------------------------
# The admin action — queued, not done inline
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_the_action_enqueues_one_task_per_ad_and_makes_no_request(ad, monkeypatch):
    """One task per ad, not one per selection: a failure then loses one lookup rather than
    the other forty-nine, and each gets its own row in the run log."""
    other = Ad.objects.create(
        external_id=556, marketplace=Marketplace.BAZOS, url="https://example.test/2",
        name="Bosch GSB 18", price_raw="2 000 Kč", price=2000,
        location="Brno, 602 00", short_description="",
    )
    model_admin = dj_admin.site._registry[Ad]
    # `actions` may hold callables or method names; this one is registered as a callable.
    action = next(
        a for a in (model_admin.actions or ())
        if callable(a) and getattr(a, "__name__", "") == "look_up_reference_price"
    )
    request, messages_sent = _request_capturing_messages(model_admin, monkeypatch)

    with patch("refprice.admin.async_task") as async_task, \
         patch("refprice.services.lookup_reference_price") as resolve_mock:
        action(model_admin, request, Ad.objects.filter(pk__in=[ad.pk, other.pk]))

    assert {call.args for call in async_task.call_args_list} == {
        (LOOKUP_REFERENCE_PRICE, ad.pk), (LOOKUP_REFERENCE_PRICE, other.pk)
    }
    resolve_mock.assert_not_called()
    level, text = messages_sent[0]
    assert "Queued 2" in text
    # INFO, not SUCCESS, and the word is "queued": the outcome lives on the Success/Failure
    # rows, so claiming a lookup happened here would be a lie whenever the cluster is down.
    assert level == INFO
    assert "Queued" in text and "looked up" not in text


def _request_capturing_messages(model_admin, monkeypatch):
    """Via monkeypatch so the override is undone.

    `dj_admin.site._registry[Ad]` is one shared instance for the whole session, so a plain
    assignment here would leave every later test's `message_user` writing into this list.
    """
    from django.test import RequestFactory

    request = RequestFactory().post("/admin/bazos/ad/")
    captured: list[tuple[int, str]] = []
    monkeypatch.setattr(
        model_admin,
        "message_user",
        lambda req, msg, level=INFO, **kw: captured.append((level, msg)),
    )
    return request, captured
