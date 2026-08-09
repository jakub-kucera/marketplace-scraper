"""Tests for bazos/admin.py — QueryAdminForm's per-query filter rule picker.

Covers the admin-friendly checkbox UI for `Query.filter_rule_names`, backed by
`bazos.filters.RULE_REGISTRY` (see PROMPTS.md P17).
"""
import json

import pytest
from django import forms as dj_forms
from django.contrib.auth import get_user_model
from django.forms import model_to_dict

from bazos.admin import QueryAdminForm
from bazos.filters import RULE_REGISTRY
from senders.models import Discord


@pytest.fixture
def valid_query_data(query):
    """A full, form-valid data dict for `query`.

    Two quirks of building POST-style data from `model_to_dict` rather than an
    actual HTML submission:
    - `Query.sender` has no `blank=True` despite `null=True`, so the form
      requires a value even though the DB allows NULL — give it a real one.
    - The default `JSONField` form widget round-trips through a JSON *string*;
      `model_to_dict` gives the raw Python value instead, and an empty list
      lands in `to_python`'s `empty_values` and gets coerced to `None`
      (violating the NOT NULL column). Serialize those fields as real HTML
      form submissions would.
    """
    sender = Discord.objects.create(channel_name="test", url="https://discord.test/webhook")
    data = model_to_dict(query)
    data["sender"] = sender.pk
    data["filter_blocklist"] = json.dumps(data["filter_blocklist"])
    data["filter_required"] = json.dumps(data["filter_required"])
    # model_to_dict gives None for empty FKs; a real <select> submits "" instead,
    # and the test client's multipart encoder rejects None outright.
    return {key: ("" if value is None else value) for key, value in data.items()}


# ---------------------------------------------------------------------------
# Field definition (no DB required)
# ---------------------------------------------------------------------------

def test_filter_rule_names_choices_match_registry():
    choices = QueryAdminForm.base_fields["filter_rule_names"].choices
    assert [value for value, _label in choices] == list(RULE_REGISTRY)


def test_filter_rule_names_uses_checkboxes():
    field = QueryAdminForm.base_fields["filter_rule_names"]
    assert isinstance(field.widget, dj_forms.CheckboxSelectMultiple)


def test_filter_rule_names_not_required():
    """Empty selection must be allowed — it means "all default rules"."""
    assert QueryAdminForm.base_fields["filter_rule_names"].required is False


# ---------------------------------------------------------------------------
# Rendering existing selections (prepopulating the form)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_form_prepopulates_selected_rules_from_instance(query):
    query.filter_rule_names = ["price_range", "price_drop"]
    query.save()

    form = QueryAdminForm(instance=query)

    assert form.initial["filter_rule_names"] == ["price_range", "price_drop"]


@pytest.mark.django_db
def test_form_prepopulates_empty_when_no_rules_set(query):
    form = QueryAdminForm(instance=query)
    assert form.initial["filter_rule_names"] == []


# ---------------------------------------------------------------------------
# Saving selections
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_form_saves_selected_rule_subset(query, valid_query_data):
    valid_query_data["filter_rule_names"] = ["blocklist_keyword", "required_keyword"]

    form = QueryAdminForm(data=valid_query_data, instance=query)

    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.filter_rule_names == ["blocklist_keyword", "required_keyword"]


@pytest.mark.django_db
def test_form_saves_empty_selection_as_empty_list(query, valid_query_data):
    query.filter_rule_names = ["price_range"]
    query.save()
    valid_query_data["filter_rule_names"] = []

    form = QueryAdminForm(data=valid_query_data, instance=query)

    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.filter_rule_names == []


@pytest.mark.django_db
def test_form_rejects_unknown_rule_name(query, valid_query_data):
    """Unlike raw JSON, the checkbox UI can't submit a typo'd rule name —
    but guard the form-level validation directly in case choices ever
    drift out of sync with RULE_REGISTRY."""
    valid_query_data["filter_rule_names"] = ["not_a_real_rule"]

    form = QueryAdminForm(data=valid_query_data, instance=query)

    assert not form.is_valid()
    assert "filter_rule_names" in form.errors


# ---------------------------------------------------------------------------
# End-to-end through the real admin URL (Client, not just the form class)
# ---------------------------------------------------------------------------

@pytest.fixture
def admin_client_logged_in(db, client):
    User = get_user_model()
    user = User.objects.create_superuser(username="admin", email="admin@test.local", password="password")
    client.force_login(user)
    return client


@pytest.mark.django_db
def test_change_page_renders_a_checkbox_per_rule(admin_client_logged_in, query):
    response = admin_client_logged_in.get(f"/admin/bazos/query/{query.pk}/change/")
    assert response.status_code == 200
    content = response.content.decode()
    for name in RULE_REGISTRY:
        assert f'value="{name}"' in content, f"no checkbox rendered for rule {name!r}"


@pytest.mark.django_db
def test_change_page_checks_existing_selection(admin_client_logged_in, query):
    query.filter_rule_names = ["price_range"]
    query.save()

    response = admin_client_logged_in.get(f"/admin/bazos/query/{query.pk}/change/")
    content = response.content.decode()

    def input_tag(rule_name):
        start = content.index(f'value="{rule_name}"')
        return content[start : content.index(">", start) + 1]

    assert "checked" in input_tag("price_range")
    assert "checked" not in input_tag("blocklist_keyword")


@pytest.mark.django_db
def test_change_page_post_updates_rule_selection(admin_client_logged_in, query, valid_query_data):
    valid_query_data["filter_rule_names"] = ["publisher_blocklist", "price_drop"]

    response = admin_client_logged_in.post(f"/admin/bazos/query/{query.pk}/change/", data=valid_query_data)

    assert response.status_code == 302, response.context["adminform"].form.errors if response.status_code == 200 else None
    query.refresh_from_db()
    assert query.filter_rule_names == ["publisher_blocklist", "price_drop"]


# ---------------------------------------------------------------------------
# QueryAdmin.ad_count — how many ads this query has found
# ---------------------------------------------------------------------------

@pytest.fixture
def query_admin():
    from django.contrib.admin.sites import AdminSite

    from bazos.admin import QueryAdmin
    from bazos.models import Query

    return QueryAdmin(Query, AdminSite())


@pytest.mark.django_db
def test_ad_count_counts_this_querys_ads(query_admin, query, make_ad, rf):
    for bazos_id in (1, 2, 3):
        make_ad(query, bazos_id).save()

    row = query_admin.get_queryset(rf.get("/")).get(pk=query.pk)

    assert query_admin.ad_count(row) == 3


@pytest.mark.django_db
def test_ad_count_is_not_inflated_by_query_runs(query_admin, query, make_ad, rf):
    """`ad_count` aggregates over `ads` while `last_run` aggregates over `runs` in the same
    queryset — the two joins multiply rows, so a non-distinct Count would report 6 here.
    """
    from django.utils import timezone

    from bazos.models import QueryRun

    for bazos_id in (1, 2, 3):
        make_ad(query, bazos_id).save()
    for _ in range(2):
        QueryRun.objects.create(query=query, run_start=timezone.now(), run_end=timezone.now())

    row = query_admin.get_queryset(rf.get("/")).get(pk=query.pk)

    assert query_admin.ad_count(row) == 3
    assert row.last_run is not None  # the other annotation still works


@pytest.mark.django_db
def test_ad_count_is_zero_for_a_query_with_no_ads(query_admin, query, rf):
    row = query_admin.get_queryset(rf.get("/")).get(pk=query.pk)

    assert query_admin.ad_count(row) == 0


@pytest.mark.django_db
def test_changelist_renders_the_ad_count_column(admin_client_logged_in, query, make_ad):
    make_ad(query, 1).save()

    response = admin_client_logged_in.get("/admin/bazos/query/")

    assert response.status_code == 200
    assert "column-ad_count" in response.content.decode()
