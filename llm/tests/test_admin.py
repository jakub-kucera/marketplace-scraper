"""`LLMCall` admin — the cost surface.

The generic `test_every_registered_changelist_renders` in `bazos/tests/test_admin.py`
already asserts this page returns 200. What it cannot catch is the two traps CLAUDE.md
names: a stock `ModelAdmin` renders unthemed but still 200s, and the Unfold sidebar is
hand-maintained, so a newly registered model never appears in it on its own.
"""
import pytest
from django.contrib import admin as dj_admin
from django.contrib.auth import get_user_model
from django.test import RequestFactory
from django.urls import reverse
from unfold.admin import ModelAdmin as UnfoldModelAdmin

from llm.models import LLMCall, LLMOutcome

pytestmark = pytest.mark.django_db


@pytest.fixture()
def superuser():
    return get_user_model().objects.create_superuser(
        username="llm-admin", email="a@test.local", password="password"
    )


@pytest.fixture()
def admin_client_logged_in(client, superuser):
    client.force_login(superuser)
    return client


@pytest.fixture()
def admin_request(superuser):
    request = RequestFactory().get("/admin/llm/llmcall/")
    request.user = superuser
    return request


def test_llmcall_is_registered():
    assert LLMCall in dj_admin.site._registry


def test_it_subclasses_the_themed_base():
    """A stock ModelAdmin still returns 200 — only this assertion catches it."""
    assert isinstance(dj_admin.site._registry[LLMCall], UnfoldModelAdmin)


def test_it_appears_in_the_hand_maintained_sidebar():
    from django.conf import settings
    sidebar: dict = settings.UNFOLD["SIDEBAR"]
    links = [str(item["link"]) for group in sidebar["navigation"] for item in group["items"]]
    assert str(reverse("admin:llm_llmcall_changelist")) in links


def test_the_changelist_renders_with_rows(admin_client_logged_in):
    LLMCall.objects.create(
        prompt_name="refprice_adjudicate", prompt_version="v1", provider="ANTHROPIC",
        model="claude-haiku-4-5-20251001", tokens_in=300, tokens_out=40,
        cost_usd="0.000500", latency_ms=800, outcome=LLMOutcome.OK,
    )
    url = reverse("admin:llm_llmcall_changelist")
    assert admin_client_logged_in.get(url).status_code == 200


def test_the_log_is_read_only_even_for_a_superuser(admin_request):
    """An audit log you can edit is not an audit log."""
    opts = dj_admin.site._registry[LLMCall]
    assert opts.has_add_permission(admin_request) is False
    assert opts.has_change_permission(admin_request) is False
