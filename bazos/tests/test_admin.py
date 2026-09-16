"""Tests for bazos/admin.py — QueryAdminForm's per-query filter rule picker.

Covers the admin-friendly checkbox UI for `Query.filter_rule_names`, backed by
`bazos.filters.RULE_REGISTRY` (see PROMPTS.md P17).
"""
import json
from datetime import timedelta

import pytest
from bs4 import BeautifulSoup
from django import forms as dj_forms
from django.contrib.auth import get_user_model
from django.forms import model_to_dict
from django.urls import reverse
from django.utils import timezone

from bazos.admin import AdAdmin, QueryAdmin, QueryAdminForm, QueryRunAdmin
from bazos.filters import RULE_REGISTRY
from bazos.models import Ad
from senders.models import Discord


@pytest.fixture
def valid_query_data(query):
    """A full, form-valid data dict for `query`.

    Two quirks of building POST-style data from `model_to_dict` rather than an
    actual HTML submission:
    - `Query.sender` has no `blank=True` despite `null=True`, so the form
      requires a value even though the DB allows NULL — give it a real one.
    - `QueryAdmin` has a `QueryChangeInline`, so the POST needs that formset's
      management form. A browser submission carries it in the rendered HTML; a
      hand-built dict has to add it, or the formset is invalid and the change
      view re-renders as 200 with an *empty* `form.errors` (the error is on the
      formset, not the form) — which looks exactly like a silent no-op.
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
    data.update({
        "config_history-TOTAL_FORMS": "0",
        "config_history-INITIAL_FORMS": "0",
        "config_history-MIN_NUM_FORMS": "0",
        "config_history-MAX_NUM_FORMS": "0",
    })
    # model_to_dict gives None for empty FKs; a real <select> submits "" instead,
    # and the test client's multipart encoder rejects None outright.
    return {key: ("" if value is None else value) for key, value in data.items()}


# ---------------------------------------------------------------------------
# Field definition (no DB required)
# ---------------------------------------------------------------------------

def test_filter_rule_names_choices_match_registry():
    """Choices are a callable, so a rule another app registers at AppConfig.ready() --
    after this form class is defined -- is still selectable here."""
    choices = QueryAdminForm.base_fields["filter_rule_names"].choices
    assert [value for value, _label in choices] == list(RULE_REGISTRY)


def test_an_opt_in_rule_from_another_app_is_still_selectable():
    from bazos.filters import OPT_IN_RULE_NAMES

    choices = dict(QueryAdminForm.base_fields["filter_rule_names"].choices)
    for name in OPT_IN_RULE_NAMES:
        assert name in choices


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
# JSONField "empty value" gotcha — an emptied widget round-trips as None, not
# {}/[], which would violate the NOT NULL column. clean_extra_params /
# clean_filter_blocklist / clean_filter_required all guard against this.
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_form_saves_blank_extra_params_widget_as_empty_dict(query, valid_query_data):
    valid_query_data["extra_params"] = ""  # a real, genuinely-cleared Textarea

    form = QueryAdminForm(data=valid_query_data, instance=query)

    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.extra_params == {}


@pytest.mark.django_db
def test_form_saves_blank_filter_blocklist_widget_as_empty_list(query, valid_query_data):
    valid_query_data["filter_blocklist"] = ""

    form = QueryAdminForm(data=valid_query_data, instance=query)

    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.filter_blocklist == []


@pytest.mark.django_db
def test_form_saves_blank_filter_required_widget_as_empty_list(query, valid_query_data):
    valid_query_data["filter_required"] = ""

    form = QueryAdminForm(data=valid_query_data, instance=query)

    assert form.is_valid(), form.errors
    saved = form.save()
    assert saved.filter_required == []


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
    soup = BeautifulSoup(response.content.decode(), "html.parser")

    def checkbox(rule_name):
        tag = soup.find("input", attrs={"name": "filter_rule_names", "value": rule_name})
        assert tag is not None, f"no checkbox rendered for rule {rule_name!r}"
        return tag

    # Parsed, not substring-matched: the themed widget's class list contains Tailwind
    # variants like `checked:bg-primary-600`, so `"checked" in tag` is true of every
    # checkbox whether or not the attribute is set.
    assert checkbox("price_range").has_attr("checked")
    assert not checkbox("blocklist_keyword").has_attr("checked")


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
def test_ad_count_counts_this_querys_ads(query_admin, query, make_ad, make_delivery, rf):
    for bazos_id in (1, 2, 3):
        ad = make_ad(query, bazos_id)
        ad.save()
        make_delivery(ad, query)

    row = query_admin.get_queryset(rf.get("/")).get(pk=query.pk)

    assert query_admin.ad_count(row) == 3


@pytest.mark.django_db
def test_ad_count_is_not_inflated_by_query_runs(query_admin, query, make_ad, make_delivery, rf):
    """`ad_count` counts `deliveries` while `last_run` aggregates over `runs`. Done as one
    joined queryset those two relations multiply, and a non-distinct Count reports 6 here.
    They are separate correlated subqueries now, so the counts can't interfere at all —
    this stays as the guard against anyone folding them back into one join.
    """
    from django.utils import timezone

    from bazos.models import QueryRun

    for bazos_id in (1, 2, 3):
        ad = make_ad(query, bazos_id)
        ad.save()
        make_delivery(ad, query)
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
def test_changelist_queryset_does_not_join_deliveries_or_runs(query_admin, rf):
    """Performance guard, not a style preference.

    `annotate(Count('deliveries'), Max('runs__...'))` joins both reverse relations into
    one query, so Postgres materialises a deliveries x runs product per Query row — tens
    of millions of intermediate rows once history accumulates, which is what made this
    changelist slow. Correlated subqueries read one table each through its FK index.
    """
    sql = str(query_admin.get_queryset(rf.get("/")).query)

    # get_queryset() runs before the changelist applies `list_select_related`, so a JOIN
    # here can only come from an annotation. If someone adds a select_related *inside*
    # get_queryset, relax this to assert on the two table names specifically.
    assert "JOIN" not in sql
    assert "DISTINCT" not in sql
    # Both tables are still read — as subqueries, not joins.
    assert "bazos_addelivery" in sql
    assert "bazos_queryrun" in sql


@pytest.mark.django_db
def test_last_run_prefers_run_end_but_falls_back_to_run_start(query_admin, query, rf):
    """An in-flight run has no run_end yet; the column must not go blank because of it."""
    from django.utils import timezone

    from bazos.models import QueryRun

    started = timezone.now()
    QueryRun.objects.create(query=query, run_start=started, run_end=None)

    row = query_admin.get_queryset(rf.get("/")).get(pk=query.pk)

    assert row.last_run == started


@pytest.mark.django_db
def test_changelist_renders_the_ad_count_column(admin_client_logged_in, query, make_ad):
    make_ad(query, 1).save()

    response = admin_client_logged_in.get("/admin/bazos/query/")

    assert response.status_code == 200
    assert "column-ad_count" in response.content.decode()


# ---------------------------------------------------------------------------
# AdAdmin.ordering — nulls_last (Vinted ads carry no publish_date)
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_ad_admin_ordering_puts_null_publish_date_last():
    """Plain "-publish_date" would put every null (Vinted) ad above the newest dated
    (Bazos) ad — Postgres's DESC defaults to NULLS FIRST. AdAdmin.ordering must use
    nulls_last so the changelist's "newest first" reads correctly once Vinted ads exist.
    """
    now = timezone.now()

    def make(external_id, marketplace, publish_date):
        return Ad.objects.create(
            external_id=external_id, marketplace=marketplace,
            url=f"https://example.test/{external_id}", name="x", price_raw="1 Kč",
            location="", publish_date=publish_date, short_description="", publisher_name="",
        )

    older = make(1, "bazos", now - timedelta(days=1))
    newer = make(2, "bazos", now)
    no_date = make(3, "vinted", None)

    # getattr, not AdAdmin.ordering directly: mypy can't resolve the attribute's type
    # through the base class's `# type: ignore[assignment]` on the F().desc() value.
    ordered_ids = list(Ad.objects.order_by(*getattr(AdAdmin, "ordering")).values_list("pk", flat=True))

    assert ordered_ids == [newer.pk, older.pk, no_date.pk]


# ---------------------------------------------------------------------------
# QueryAdmin ordering — the changelist as a stable control panel
# ---------------------------------------------------------------------------

@pytest.fixture
def ordering_queries(db, category):
    """Four queries spanning both sort keys that matter: enabled, then marketplace."""
    from bazos.models import Marketplace, Query

    def make(text, enabled=True, marketplace=Marketplace.BAZOS):
        return Query.objects.create(
            text=text,
            category=category,
            location_radius=25,
            enabled=enabled,
            marketplace=marketplace,
        )

    # Created in an order that no sort key would reproduce by accident, so a passing
    # assertion cannot be the `-pk` fallback in disguise.
    return {
        "disabled_bazos": make("aaa", enabled=False),
        "vinted": make("zzz", marketplace=Marketplace.VINTED),
        "bazos_b": make("bbb"),
        "bazos_a": make("aab"),
    }


@pytest.mark.django_db
def test_changelist_lists_enabled_queries_before_disabled(query_admin, ordering_queries, rf):
    """Disabled rows are dead weight on this page — and `randomly_generated` queries are
    force-disabled at the top of every pass, so this is what sinks the generated noise."""
    rows = list(query_admin.get_queryset(rf.get("/")).order_by(*query_admin.ordering))

    assert rows[-1] == ordering_queries["disabled_bazos"]
    assert all(row.enabled for row in rows[:-1])


@pytest.mark.django_db
def test_changelist_groups_by_marketplace_then_sorts_by_text(query_admin, ordering_queries, rf):
    rows = list(query_admin.get_queryset(rf.get("/")).order_by(*query_admin.ordering))

    assert rows[:3] == [
        ordering_queries["bazos_a"],   # bazos, "aab"
        ordering_queries["bazos_b"],   # bazos, "bbb"
        ordering_queries["vinted"],    # vinted sorts after bazos
    ]


@pytest.mark.django_db
def test_last_run_sorts_never_run_queries_last(query_admin, ordering_queries, rf):
    """Postgres DESC defaults to NULLS FIRST, so a bare "-last_run" would open the
    "most recently run" view on the queries that have never run at all."""
    from django.utils import timezone

    from bazos.models import QueryRun

    ran = ordering_queries["bazos_b"]
    QueryRun.objects.create(query=ran, run_start=timezone.now(), run_end=timezone.now())

    order_field = QueryAdmin.last_run.admin_order_field
    rows = list(query_admin.get_queryset(rf.get("/")).order_by(order_field))

    assert rows[0] == ran
    assert all(row.last_run is None for row in rows[1:])


@pytest.mark.django_db
def test_last_run_reversed_puts_never_run_queries_first(query_admin, ordering_queries, rf):
    """Django reverses an `OrderBy` by flipping direction *and* null placement, so the
    ascending click reads as least-recently-run first — never-run being the extreme."""
    from django.utils import timezone

    from bazos.models import QueryRun

    ran = ordering_queries["bazos_b"]
    QueryRun.objects.create(query=ran, run_start=timezone.now(), run_end=timezone.now())

    reversed_field = QueryAdmin.last_run.admin_order_field.copy()
    reversed_field.reverse_ordering()
    rows = list(query_admin.get_queryset(rf.get("/")).order_by(reversed_field))

    assert rows[-1] == ran
    assert all(row.last_run is None for row in rows[:-1])


@pytest.mark.django_db
def test_changelist_honours_the_last_run_column_sort_links(admin_client_logged_in, ordering_queries):
    """`admin_order_field` holds an `OrderBy` expression rather than a string, which is a
    branch of Django's own ordering parser — exercise the real request, both directions."""
    index = QueryAdmin.list_display.index("last_run")

    for order_param in (str(index), f"-{index}"):
        response = admin_client_logged_in.get("/admin/bazos/query/", {"o": order_param})
        assert response.status_code == 200, order_param
        assert len(response.context["cl"].result_list) == len(ordering_queries)


@pytest.fixture
def query_run_admin():
    from django.contrib.admin.sites import AdminSite

    from bazos.admin import QueryRunAdmin
    from bazos.models import QueryRun

    return QueryRunAdmin(QueryRun, AdminSite())


@pytest.mark.django_db
def test_duration_is_the_measured_run_length(query_run_admin, query, rf):
    from django.utils import timezone

    from bazos.models import QueryRun

    started = timezone.now()
    QueryRun.objects.create(query=query, run_start=started, run_end=started + timedelta(seconds=12.5))

    row = query_run_admin.get_queryset(rf.get("/")).get()

    assert row.duration == timedelta(seconds=12.5)
    assert query_run_admin.duration(row) == "12.5 s"


@pytest.mark.django_db
def test_duration_is_blank_for_a_run_that_never_ended(query_run_admin, query, rf):
    """`run_end` is nullable — a crashed or in-flight run must not read as 0.0 s."""
    from django.utils import timezone

    from bazos.models import QueryRun

    QueryRun.objects.create(query=query, run_start=timezone.now(), run_end=None)

    row = query_run_admin.get_queryset(rf.get("/")).get()

    assert row.duration is None
    assert query_run_admin.duration(row) is None


@pytest.mark.django_db
def test_duration_sorts_longest_first_with_unmeasured_runs_last(query_run_admin, query, rf):
    """Postgres DESC defaults to NULLS FIRST, so a bare "-duration" would open the
    "slowest runs" view on the runs that have no duration at all."""
    from django.utils import timezone

    from bazos.models import QueryRun

    started = timezone.now()
    short = QueryRun.objects.create(query=query, run_start=started, run_end=started + timedelta(seconds=1))
    long = QueryRun.objects.create(query=query, run_start=started, run_end=started + timedelta(seconds=90))
    unfinished = QueryRun.objects.create(query=query, run_start=started, run_end=None)

    order_field = QueryRunAdmin.duration.admin_order_field
    rows = list(query_run_admin.get_queryset(rf.get("/")).order_by(order_field))

    assert rows == [long, short, unfinished]


@pytest.mark.django_db
def test_changelist_honours_the_duration_column_sort_links(admin_client_logged_in, query):
    """`admin_order_field` holds an `OrderBy` expression rather than a string, which is a
    branch of Django's own ordering parser — exercise the real request, both directions."""
    from django.utils import timezone

    from bazos.models import QueryRun

    started = timezone.now()
    QueryRun.objects.create(query=query, run_start=started, run_end=started + timedelta(seconds=3))
    QueryRun.objects.create(query=query, run_start=started, run_end=None)

    index = QueryRunAdmin.list_display.index("duration")

    for order_param in (str(index), f"-{index}"):
        response = admin_client_logged_in.get("/admin/bazos/queryrun/", {"o": order_param})
        assert response.status_code == 200, order_param
        assert len(response.context["cl"].result_list) == 2

# ---------------------------------------------------------------------------
# QueryAdminForm — distance filter fields
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_form_normalises_the_distance_centre(query, valid_query_data):
    valid_query_data["filter_location_center"] = "110 00"
    valid_query_data["filter_location_radius"] = 10

    form = QueryAdminForm(data=valid_query_data, instance=query)

    assert form.is_valid(), form.errors
    assert form.save().filter_location_center == "11000"


@pytest.mark.django_db
def test_form_rejects_a_centre_that_is_not_a_postal_code(query, valid_query_data):
    valid_query_data["filter_location_center"] = "Praha"
    valid_query_data["filter_location_radius"] = 10

    form = QueryAdminForm(data=valid_query_data, instance=query)

    assert not form.is_valid()
    assert "filter_location_center" in form.errors


@pytest.mark.django_db
@pytest.mark.parametrize("center,radius", [("110 00", ""), ("", 10)])
def test_form_rejects_half_a_distance_filter(query, valid_query_data, center, radius):
    """Half a filter is no filter, but looks like a configured one on the change form."""
    valid_query_data["filter_location_center"] = center
    valid_query_data["filter_location_radius"] = radius

    form = QueryAdminForm(data=valid_query_data, instance=query)

    assert not form.is_valid()


@pytest.mark.django_db
def test_form_accepts_neither_field_set(query, valid_query_data):
    valid_query_data["filter_location_center"] = ""
    valid_query_data["filter_location_radius"] = ""

    form = QueryAdminForm(data=valid_query_data, instance=query)

    assert form.is_valid(), form.errors
    saved = form.save()
    assert (saved.filter_location_center, saved.filter_location_radius) == ("", None)
    

# ---------------------------------------------------------------------------
# AdAdmin — price-score columns
# ---------------------------------------------------------------------------

@pytest.fixture
def ad_admin():
    from django.contrib.admin.sites import AdminSite
    return AdAdmin(Ad, AdminSite())


@pytest.mark.django_db
def test_ad_changelist_does_not_join_price_scores(ad_admin, rf):
    """Same performance guard as QueryAdmin's, narrowed to what is actually at stake here.

    `AdAdmin` legitimately joins `bazos_addelivery` — that is `Count('deliveries',
    distinct=True)`, and its own comment explains why. What must NOT happen is a *second*
    reverse-FK join: deliveries x price_scores materialises the product per Ad row, which
    is the exact shape QueryAdmin.get_queryset was rewritten to avoid. So the scores have
    to arrive as a correlated subquery.
    """
    sql = str(ad_admin.get_queryset(rf.get("/")).query)

    assert "bazos_adpricescore" in sql, "the score columns must still read the table"
    assert 'JOIN "bazos_adpricescore"' not in sql, "scores must be a subquery, not a join"
    assert sql.count("JOIN") == 1, f"exactly one join (deliveries) expected, got: {sql}"


@pytest.mark.django_db
def test_score_columns_render_a_dash_when_nothing_scored(ad_admin, query, make_ad, rf):
    ad = make_ad(query, 1)
    ad.save()

    row = ad_admin.get_queryset(rf.get("/")).get(pk=ad.pk)

    assert ad_admin.price_discount(row) == "—"
    assert ad_admin.price_z(row) == "—"


@pytest.mark.django_db
def test_score_columns_show_the_newest_scored_row(ad_admin, query, make_ad, rf):
    from bazos.models import AdPriceScore

    ad = make_ad(query, 1)
    ad.save()
    AdPriceScore.objects.create(
        ad=ad, model_name="macbook", model_version="1",
        predicted=50_000, residual_log=-0.2, discount_pct=18.1, z_score=-2.4,
    )

    row = ad_admin.get_queryset(rf.get("/")).get(pk=ad.pk)

    assert ad_admin.price_discount(row) == "+18%"
    assert ad_admin.price_z(row) == "-2.40"


@pytest.mark.django_db
def test_score_columns_ignore_a_declined_score(ad_admin, query, make_ad, rf):
    """A declined row has null numbers; it must not blank out a real score, nor render 0."""
    from bazos.models import AdPriceScore

    ad = make_ad(query, 1)
    ad.save()
    AdPriceScore.objects.create(
        ad=ad, model_name="macbook", model_version="1",
        predicted=None, discount_pct=None, z_score=None, declined_reason="incomplete specs",
    )

    row = ad_admin.get_queryset(rf.get("/")).get(pk=ad.pk)

    assert ad_admin.price_discount(row) == "—"


# ---------------------------------------------------------------------------
# Whole-surface smoke — the admin is an operational tool, not scaffolding
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_every_registered_changelist_renders(admin_client_logged_in):
    """Every registered ModelAdmin's changelist returns 200, third-party ones included.

    The targeted tests above cover Query and Ad. This is the net for the rest: a Django
    upgrade, or a theme that replaces the admin templates, breaks a changelist somewhere
    other than the two that happen to have assertions.
    """
    from django.contrib import admin as dj_admin

    for model in dj_admin.site._registry:
        opts = model._meta
        url = reverse(f"admin:{opts.app_label}_{opts.model_name}_changelist")
        response = admin_client_logged_in.get(url)
        assert response.status_code == 200, f"{url} returned {response.status_code}"


@pytest.mark.django_db
def test_query_changelist_renders_the_force_run_button(admin_client_logged_in):
    """The button lives in a template override (templates/admin/bazos/query/change_list.html)
    that hooks Django's `object-tools-items` block. Nothing else notices if that block is
    renamed upstream — the view tests in test_force_run.py call the handler directly.
    """
    response = admin_client_logged_in.get(reverse("admin:bazos_query_changelist"))

    assert "Force Run Now" in response.content.decode()
