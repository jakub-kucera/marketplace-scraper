"""`manage.py llm_check` — the "is my key working?" command.

Goes through `llm.services.complete`, so it exercises the real budget ceiling, cache and
audit row rather than a special path that would prove nothing about production.
"""
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.test import override_settings

from llm.models import LLMCall

pytestmark = pytest.mark.django_db


def run(*args) -> str:
    out = StringIO()
    call_command("llm_check", *args, stdout=out, stderr=out)
    return out.getvalue()


@override_settings(LLM_PROVIDER="NULL")
def test_it_reports_the_configured_provider():
    assert "NULL" in run()


@override_settings(LLM_PROVIDER="NULL")
def test_the_default_provider_reports_a_decline_not_an_error():
    """`LLM_PROVIDER=NULL` is a correct configuration, not a broken one."""
    assert "DECLINED" in run()


@override_settings(LLM_PROVIDER="NULL")
def test_it_still_writes_an_audit_row():
    run()
    assert LLMCall.objects.filter(prompt_name="llm_check").exists()


@override_settings(LLM_PROVIDER="NULL")
def test_it_shows_month_to_date_spend_against_the_ceiling():
    assert "this month" in run()


@override_settings(LLM_PROVIDER="GEMINI", GEMINI_API_KEY="abcdef1234567890",
                   LLM_MODEL="gemini-test")
def test_it_never_prints_the_key():
    with patch("llm.providers.gemini.requests.post") as post:
        post.return_value = MagicMock(status_code=403)
        output = run()
    assert "abcdef1234567890" not in output
    assert "7890" in output  # last four is enough to tell "wrong key" from "no key"


@override_settings(LLM_PROVIDER="GEMINI", GEMINI_API_KEY="", LLM_API_KEY="")
def test_it_says_when_no_key_is_set():
    assert "NOT SET" in run()


@override_settings(LLM_PROVIDER="GEMINI", GEMINI_API_KEY="k", LLM_MODEL="gemini-test")
def test_model_override_applies_to_the_call():
    with patch("llm.providers.gemini.requests.post") as post:
        post.return_value = MagicMock(status_code=400)
        output = run("--model", "gemini-other")
    assert "gemini-other" in output


@override_settings(LLM_PROVIDER="GEMINI", GEMINI_API_KEY="k")
def test_models_lists_what_the_key_can_reach():
    payload = {"models": [
        {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
        {"name": "models/embedding-001", "supportedGenerationMethods": ["embedContent"]},
    ]}
    response = MagicMock(status_code=200)
    response.json.return_value = payload
    with patch("llm.providers.gemini.requests.get", return_value=response):
        output = run("--models")
    assert "gemini-2.5-flash" in output
    assert "embedding-001" not in output, "only generateContent models are usable here"


@override_settings(LLM_PROVIDER="NULL")
def test_models_says_so_when_the_provider_cannot_list():
    assert "cannot list models" in run("--models")
