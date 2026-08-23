"""Tests for migration 0026_addelivery's backfill.

The backfill reads `Ad.status`/`Ad.query` (and friends) — fields that migration 0028
later drops from `Ad`. So, unlike `test_sentinel_publisher_migration.py` (whose migration
only touches fields that survive to the current model), stubbing `apps.get_model` with the
*live* `bazos.models.Ad` doesn't work here post-Stage-D: those attributes no longer exist
on it. These tests instead roll the schema back to 0025 (just before 0026) with Django's
own `MigrationExecutor`, build fixtures through the *historical* model classes at that
point (which do have `Ad.status`/`Ad.query`), then migrate forward through the real 0026
and assert against the live `AdDelivery` model (unaffected by Stage D).
"""
import importlib
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import IntegrityError
from django.utils import timezone

from bazos.models import Ad, AdDelivery, AdStatus

migration = importlib.import_module("bazos.migrations.0026_addelivery")


def _old_fixtures(apps):
    Section = apps.get_model("bazos", "Section")
    Category = apps.get_model("bazos", "Category")
    Query = apps.get_model("bazos", "Query")

    section = Section.objects.create(name="PC", bazos_id="PC", url="pc")
    category = Category.objects.create(name="Notebooky", url="notebook", bazos_id=10, section=section)
    query = Query.objects.create(
        text="macbook", category=category, location_center="12345", location_radius=25,
        price_lower=0, price_upper=0, new_query=False, ignore_first_run=True,
    )
    return query


def _old_ad(apps, query, bazos_id, **extra):
    Ad_ = apps.get_model("bazos", "Ad")
    fields = dict(
        external_id=bazos_id, marketplace="bazos",
        url=f"https://pc.bazos.cz/inzerat/{bazos_id}/test.php", name=f"Ad {bazos_id}",
        price_raw="1000 Kč", location="Praha", view_count=10, publish_date=timezone.now(),
        topped=False, short_description="Short desc", publisher_name="Seller", query=query,
    )
    fields.update(extra)
    return Ad_.objects.create(**fields)


@pytest.fixture
def old_state(transactional_db):
    """Historical model classes as of migration 0025 — before AdDelivery exists.

    Leaves the DB at 0025; the test migrates forward through 0026 itself. The `finally`
    restores the DB to latest even on a failing test, since `transactional_db` doesn't
    roll DDL back the way plain `db` would.
    """
    executor = MigrationExecutor(connection)
    executor.migrate([("bazos", "0025_drop_sentinel_publishers")])
    state = executor.loader.project_state(("bazos", "0025_drop_sentinel_publishers"))
    try:
        yield state.apps
    finally:
        call_command("migrate", verbosity=0)


def migrate_to_0026():
    call_command("migrate", "bazos", "0026_addelivery", verbosity=0)


@pytest.mark.django_db
def test_backfill_creates_one_delivery_per_ad(old_state):
    query = _old_fixtures(old_state)
    ads = [_old_ad(old_state, query, bazos_id) for bazos_id in (1, 2, 3)]

    migrate_to_0026()

    assert AdDelivery.objects.count() == 3
    for ad in ads:
        assert AdDelivery.objects.filter(ad_id=ad.pk, query_id=query.pk).exists()


@pytest.mark.django_db
def test_backfill_copies_pipeline_state(old_state):
    query = _old_fixtures(old_state)
    sent_at = timezone.now()
    ad = _old_ad(
        old_state, query, bazos_id=111,
        status="SENT", filter_reason="some reason", sent_at=sent_at, send_attempts=3,
    )

    migrate_to_0026()

    delivery = AdDelivery.objects.get(ad_id=ad.pk)
    assert delivery.status == AdStatus.SENT
    assert delivery.filter_reason == "some reason"
    assert delivery.sent_at == sent_at
    assert delivery.send_attempts == 3


@pytest.mark.django_db
def test_backfill_preserves_ad_created_timestamp_for_queue_ordering(old_state):
    query = _old_fixtures(old_state)
    ad = _old_ad(old_state, query, bazos_id=111)
    old_created = timezone.now() - timedelta(days=30)
    type(ad).objects.filter(pk=ad.pk).update(created=old_created)

    migrate_to_0026()

    delivery = AdDelivery.objects.get(ad_id=ad.pk)
    # .values_list, not .get(): a plain Ad.objects.get() SELECTs every field currently
    # defined on the live model (e.g. price/price_type from migration 0032), and the
    # physical table here is frozen at 0026's schema, which predates them.
    persisted_ad_created = Ad.objects.filter(pk=ad.pk).values_list("created", flat=True).get()
    assert delivery.created == persisted_ad_created == old_created


@pytest.mark.django_db
def test_backfill_does_not_touch_other_ads(old_state):
    """A sanity check that the backfill only ever creates AdDelivery rows — it must not
    mutate the Ad rows it reads (there's nothing on Ad left for it to write to, post
    Stage D, but this pins that the loop is read-only over Ad)."""
    query = _old_fixtures(old_state)
    solo = _old_ad(old_state, query, bazos_id=111, status="APPROVED")

    migrate_to_0026()

    assert Ad.objects.filter(pk=solo.pk).exists()
    assert Ad.objects.count() == 1


@pytest.mark.django_db
def test_reverse_deletes_all_deliveries(query, make_ad, make_delivery):
    """The RunPython's own reverse (`delete_all_deliveries`), invoked directly rather
    than via a full `migrate` rollback: it only touches AdDelivery, which — unlike
    Ad.status/Ad.query — survives Stage D untouched, so the live model is a safe stand-in
    here without needing the historical-schema dance `backfill_deliveries` requires.
    """
    ad = make_ad(query, bazos_id=111)
    ad.save()
    make_delivery(ad, query)
    assert AdDelivery.objects.exists()

    class _StubApps:
        def get_model(self, app_label, model_name):
            assert app_label == "bazos"
            return AdDelivery

    migration.delete_all_deliveries(_StubApps(), schema_editor=None)

    assert not AdDelivery.objects.exists()


@pytest.mark.django_db
def test_unique_delivery_per_ad_query_constraint(query, make_ad, make_delivery):
    """Live-schema test: confirms the constraint added alongside AdDelivery still holds."""
    ad = make_ad(query, bazos_id=111)
    ad.save()
    make_delivery(ad, query)

    with pytest.raises(IntegrityError):
        AdDelivery.objects.create(ad=ad, query=query)
