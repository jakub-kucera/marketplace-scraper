"""Tests for `QueryChange` — the per-`Query` config edit log.

Two halves: the diff recording on `Query.save()` (what gets a row, what deliberately does
not), and the admin surfaces that read it back.
"""
import pytest
from django.contrib import admin as django_admin
from django.contrib.auth import get_user_model

from bazos.admin import QueryChangeInline, format_change_value, render_change_diff
from bazos.models import Category, Marketplace, Query, QueryChange
from senders.models import Discord


@pytest.fixture
def superuser(db):
    return get_user_model().objects.create_superuser(
        username="history-admin", email="admin@test.local", password="password"
    )


@pytest.fixture
def admin_client_logged_in(client, superuser):
    client.force_login(superuser)
    return client


def reload(query):
    """Re-read through the ORM, so the instance carries a fresh config snapshot."""
    return Query.objects.get(pk=query.pk)


# ---------------------------------------------------------------------------
# What gets recorded
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_editing_a_tracked_field_records_one_change(query):
    query = reload(query)
    query.price_upper = 25000
    query.save()

    change = QueryChange.objects.get()
    assert change.query == query
    assert change.changes == {"price_upper": {"old": 0, "new": 25000}}


@pytest.mark.django_db
def test_several_fields_in_one_save_are_one_row(query):
    query = reload(query)
    query.text = "thinkpad"
    query.enabled = False
    query.filter_required = ["x1", "carbon"]
    query.save()

    change = QueryChange.objects.get()
    assert change.changes == {
        "text": {"old": "macbook", "new": "thinkpad"},
        "enabled": {"old": True, "new": False},
        "filter_required": {"old": [], "new": ["x1", "carbon"]},
    }


@pytest.mark.django_db
def test_saving_without_changing_anything_records_nothing(query):
    reload(query).save()
    assert QueryChange.objects.count() == 0


@pytest.mark.django_db
def test_creating_a_query_records_nothing(category):
    Query.objects.create(text="new", category=category, location_radius=25)
    assert QueryChange.objects.count() == 0


@pytest.mark.django_db
def test_repeated_edits_accumulate_newest_first(query):
    query = reload(query)
    query.price_upper = 100
    query.save()
    query.price_upper = 200
    query.save()

    changes = list(QueryChange.objects.all())  # Meta.ordering = -created
    assert [c.changes["price_upper"]["new"] for c in changes] == [200, 100]
    assert changes[0].changes["price_upper"]["old"] == 100


@pytest.mark.django_db
def test_foreign_keys_are_recorded_by_id(query, section):
    other = Category.objects.create(
        name="Servery", url="server", bazos_id=11, section=section
    )
    old_category_id = query.category_id

    query = reload(query)
    query.category = other
    query.save()

    change = QueryChange.objects.get()
    assert change.changes == {
        "category_id": {"old": old_category_id, "new": other.pk}
    }


@pytest.mark.django_db
def test_sender_assignment_is_recorded(query):
    discord = Discord.objects.create(channel_name="c", url="https://discord.test/hook")

    query = reload(query)
    query.sender = discord
    query.save()

    assert QueryChange.objects.get().changes == {
        "sender_id": {"old": None, "new": discord.pk}
    }


@pytest.mark.django_db
def test_in_place_mutation_of_a_json_field_is_detected(query):
    """The snapshot is a deep copy, so `.append()` on a JSON list still diffs.

    A shallow snapshot would hold the *same* list object the caller mutated, the
    comparison would be `["dell"] != ["dell"]` and the edit would vanish.
    """
    query = reload(query)
    query.filter_blocklist.append("dell")
    query.save()

    assert QueryChange.objects.get().changes == {
        "filter_blocklist": {"old": [], "new": ["dell"]}
    }


# ---------------------------------------------------------------------------
# What is deliberately NOT recorded
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_new_query_flag_is_not_tracked(query):
    """`ScrapeRunner` saves every query after every successful run purely to persist
    this flip — tracking it would write a row per query per pass."""
    query = reload(query)
    query.new_query = True
    query.save()

    assert QueryChange.objects.count() == 0


@pytest.mark.django_db
def test_randomly_generated_flag_is_not_tracked(query):
    query = reload(query)
    query.randomly_generated = True
    query.save()

    assert QueryChange.objects.count() == 0


@pytest.mark.django_db
def test_queryset_update_is_invisible(query):
    """Documented blind spot: `.update()` never calls `save()`."""
    Query.objects.filter(pk=query.pk).update(price_upper=999)
    assert QueryChange.objects.count() == 0


@pytest.mark.django_db
def test_update_fields_limits_the_diff_to_what_was_written(query):
    """A field outside `update_fields` is not persisted, so claiming it changed would
    describe a database state that never existed."""
    query = reload(query)
    query.price_upper = 5000
    query.text = "not saved"
    query.save(update_fields=["price_upper"])

    assert QueryChange.objects.get().changes == {"price_upper": {"old": 0, "new": 5000}}
    assert reload(query).text == "macbook"


@pytest.mark.django_db
def test_update_fields_touching_only_untracked_fields_records_nothing(query):
    query = reload(query)
    query.new_query = True
    query.save(update_fields=["new_query"])

    assert QueryChange.objects.count() == 0


@pytest.mark.django_db
def test_instance_built_in_memory_is_not_logged(query):
    """No snapshot means no known "old" value; a fabricated change-from-nothing would be
    worse than the gap."""
    detached = Query(
        pk=query.pk,
        text="ghost",
        location_radius=25,
        # TimeStampedModel only fills these on insert; this instance updates an existing
        # row, so carry them over or the NOT NULL columns get nulled out.
        created=query.created,
        modified=query.modified,
    )
    detached._state.adding = False
    detached.save()

    assert QueryChange.objects.count() == 0


# ---------------------------------------------------------------------------
# Snapshot bookkeeping
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_snapshot_is_rebaselined_after_a_save(query):
    """Two saves of the same value must not log the second one."""
    query = reload(query)
    query.price_upper = 4200
    query.save()
    query.save()

    assert QueryChange.objects.count() == 1


@pytest.mark.django_db
def test_refresh_from_db_rebaselines_the_snapshot(query):
    """`_run_query_with_rotation` refreshes a query between blacklist retries; a stale
    snapshot would then diff against the pre-refresh row."""
    query = reload(query)
    Query.objects.filter(pk=query.pk).update(price_upper=777)
    query.refresh_from_db()
    query.save()

    assert QueryChange.objects.count() == 0


@pytest.mark.django_db
def test_deferred_fields_do_not_break_saving(query):
    """`.only()` loads a subset; the snapshot must cover exactly that subset."""
    partial = Query.objects.only("pk", "price_upper").get(pk=query.pk)
    partial.price_upper = 31000
    partial.save()

    assert QueryChange.objects.get().changes == {
        "price_upper": {"old": 0, "new": 31000}
    }


# ---------------------------------------------------------------------------
# Surviving the query
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_change_survives_the_query_being_deleted(query):
    query = reload(query)
    query.marketplace = Marketplace.VINTED
    query.save()
    label = QueryChange.objects.get().query_label

    query.delete()

    change = QueryChange.objects.get()
    assert change.query is None
    assert change.query_label == label != ""
    assert change.changes["marketplace"]["new"] == Marketplace.VINTED


@pytest.mark.django_db
def test_query_label_snapshots_the_post_save_state(query):
    query = reload(query)
    query.text = "framework 13"
    query.save()

    assert "framework 13" in QueryChange.objects.get().query_label


@pytest.mark.django_db
def test_query_label_is_truncated_to_the_column_width(category):
    query = Query.objects.create(text="a", category=category, location_radius=25)
    query = reload(query)
    query.text = "x" * 120  # Query.text max_length
    query.save()

    label = QueryChange.objects.get().query_label
    assert len(label) <= QueryChange.LABEL_MAX_LENGTH


# ---------------------------------------------------------------------------
# Model rendering helpers
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_changed_fields_uses_the_tracked_field_order_not_insertion_order(query):
    query = reload(query)
    query.sender = Discord.objects.create(channel_name="c", url="https://d.test/h")
    query.enabled = False
    query.text = "zzz"
    query.save()

    # text is declared before enabled, which is declared before sender_id.
    assert QueryChange.objects.get().changed_fields == ["text", "enabled", "sender_id"]


@pytest.mark.django_db
def test_summary_renders_old_and_new(query):
    query = reload(query)
    query.price_lower = 1000
    query.price_upper = 2000
    query.save()

    summary = QueryChange.objects.get().summary
    assert "price_lower: 0 -> 1000" in summary
    assert "price_upper: 0 -> 2000" in summary


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

def test_format_change_value_renders_json_not_repr():
    assert format_change_value(None) == "null"
    assert format_change_value(["dell", "hp"]) == '["dell", "hp"]'
    assert format_change_value("macbook") == '"macbook"'


def test_format_change_value_elides_long_values():
    rendered = format_change_value(["x" * 200])
    assert len(rendered) <= 80
    assert rendered.endswith("…")


def test_format_change_value_keeps_non_ascii_readable():
    assert format_change_value("příliš") == '"příliš"'


@pytest.mark.django_db
def test_render_change_diff_shows_field_old_and_new(query):
    query = reload(query)
    query.price_upper = 12345
    query.save()

    html = render_change_diff(QueryChange.objects.get())
    assert "price_upper" in html
    assert "12345" in html
    # The old value is struck through rather than colour-coded, so the dark theme is fine.
    assert "<s>0</s>" in html


def test_render_change_diff_handles_an_empty_diff():
    assert render_change_diff(QueryChange(changes={})) == "—"


@pytest.mark.django_db
def test_inline_caps_the_rows_it_renders(query, rf, superuser):
    query = reload(query)
    for i in range(QueryChangeInline.MAX_ROWS + 5):
        query.price_upper = i + 1
        query.save()

    inline = QueryChangeInline(Query, django_admin.site)
    request = rf.get("/")
    request.user = superuser  # InlineModelAdmin.get_queryset does a permission check
    assert inline.get_queryset(request).count() == QueryChangeInline.MAX_ROWS


@pytest.mark.django_db
def test_query_change_changelist_renders(admin_client_logged_in, query):
    query = reload(query)
    query.text = "surface laptop"
    query.save()

    response = admin_client_logged_in.get("/admin/bazos/querychange/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "surface laptop" in content
    assert "text" in content


@pytest.mark.django_db
def test_query_change_admin_is_read_only(admin_client_logged_in, query):
    query = reload(query)
    query.enabled = False
    query.save()
    change = QueryChange.objects.get()

    assert admin_client_logged_in.get("/admin/bazos/querychange/add/").status_code == 403
    response = admin_client_logged_in.get(f"/admin/bazos/querychange/{change.pk}/change/")
    # Read-only rows render through the history view; the change form redirects away.
    assert response.status_code in (200, 302)


@pytest.mark.django_db
def test_query_change_page_shows_the_history_inline(admin_client_logged_in, query):
    query = reload(query)
    query.location_center = "60200"
    query.save()

    response = admin_client_logged_in.get(f"/admin/bazos/query/{query.pk}/change/")
    assert response.status_code == 200
    content = response.content.decode()
    assert "Recent config changes" in content
    assert "location_center" in content
    assert "Browse 1 change" in content


@pytest.mark.django_db
def test_query_changelist_shows_load_full_description(admin_client_logged_in, query):
    response = admin_client_logged_in.get("/admin/bazos/query/")
    assert response.status_code == 200
    assert "column-load_full_description" in response.content.decode()
