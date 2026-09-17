"""Tests for the LLM backend canary."""
from importlib import import_module
from unittest.mock import patch

import pytest
from django.test import override_settings

from llm.jobs import LLM_CHECK, llm_check


def test_the_task_path_resolves():
    module_path, _, attribute = LLM_CHECK.rpartition(".")
    assert callable(getattr(import_module(module_path), attribute))


@pytest.mark.django_db
def test_the_schedule_is_registered_from_this_app():
    from bazos.jobs import SCHEDULES

    assert SCHEDULES["llm-check"].func == LLM_CHECK


def test_bazos_jobs_does_not_import_llm():
    """The dependency points inward, which is what `register_schedule` is for."""
    from refprice.tests.import_direction import modules_imported_by

    assert "llm" not in modules_imported_by("jobs.py")


@override_settings(LLM_PROVIDER="NULL")
@pytest.mark.django_db
def test_the_default_provider_is_skipped_rather_than_called():
    """`NullProvider` declines every call and opens no socket, so calling it would prove
    nothing while filling the run log with a weekly row that always says the same thing.
    Silence about a backend nobody configured is correct; a green row implying a working
    backend is not."""
    with patch("llm.jobs.call_command") as call:
        result = llm_check()

    call.assert_not_called()
    assert "skipped" in result


@override_settings(LLM_PROVIDER="")
@pytest.mark.django_db
def test_an_unset_provider_is_treated_as_null():
    with patch("llm.jobs.call_command") as call:
        assert "skipped" in llm_check()

    call.assert_not_called()


@override_settings(LLM_PROVIDER="GEMINI")
@pytest.mark.django_db
def test_a_configured_provider_is_actually_checked():
    with patch("llm.jobs.call_command") as call:
        result = llm_check()

    assert call.call_args.args[0] == "llm_check"
    assert "GEMINI" in result
