"""Tests for migration 0027_merge_duplicate_ads.

Unlike the other migration tests in this suite (test_sentinel_publisher_migration.py,
test_addelivery_migration.py), this migration both mutates data *and* adds a schema
constraint in the same step — and the constraint it adds is exactly what would forbid
creating the duplicate `Ad` rows this migration exists to clean up. Calling the RunPython
function directly against the live (fully-migrated) schema doesn't work here, because the
live schema already has `unique_ad_per_marketplace`.

So these tests roll the schema back to migration 0026 (just before 0027) with Django's own
`MigrationExecutor`, create duplicate `Ad` rows through the *historical* model classes at
that point (no constraint yet), then migrate forward through the real 0027 migration —
exercising both the RunPython merge and the AddConstraint exactly as `migrate` would run
them in production.
"""
import pytest
from django.core.management import call_command
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.db.utils import IntegrityError
from django.utils import timezone

from marketplace.models import Ad, AdDelivery, PriceChange


def _old_fixtures(apps):
    """A (section, category, query, other_query) tuple built from historical models."""
    Section = apps.get_model("bazos", "Section")
    Category = apps.get_model("bazos", "Category")
    Query = apps.get_model("bazos", "Query")

    section = Section.objects.create(name="PC", bazos_id="PC", url="pc")
    category = Category.objects.create(name="Notebooky", url="notebook", bazos_id=10, section=section)
    query = Query.objects.create(
        text="macbook", category=category, location_center="12345", location_radius=25,
        price_lower=0, price_upper=0, new_query=False, ignore_first_run=True,
    )
    other_query = Query.objects.create(
        text="thinkpad", category=category, location_center="12345", location_radius=25,
        price_lower=0, price_upper=0, new_query=False, ignore_first_run=True,
    )
    return query, other_query


def _old_ad(apps, query, bazos_id, price_raw="1000 Kč"):
    Ad_ = apps.get_model("bazos", "Ad")
    return Ad_.objects.create(
        external_id=bazos_id, marketplace="bazos",
        url=f"https://pc.bazos.cz/inzerat/{bazos_id}/test.php", name=f"Ad {bazos_id}",
        price_raw=price_raw, location="Praha", view_count=10, publish_date=timezone.now(),
        topped=False, short_description="Short desc", publisher_name="Seller", query=query,
    )


def _old_delivery(apps, ad, query, status="PENDING"):
    AdDelivery_ = apps.get_model("bazos", "AdDelivery")
    return AdDelivery_.objects.create(ad=ad, query=query, status=status)


def _old_price_change(apps, ad, old_price, new_price):
    PriceChange_ = apps.get_model("bazos", "PriceChange")
    return PriceChange_.objects.create(ad=ad, old_price=old_price, new_price=new_price)


@pytest.fixture
def old_state(transactional_db):
    """Historical model classes as of migration 0026 — no unique_ad_per_marketplace yet.

    Leaves the DB at 0026; the test itself migrates forward through 0027 (the migration
    under test). The `finally` re-migrates to latest even if a test fails partway, so a
    failure here can't leave a half-migrated schema for the next test in the session
    (`transactional_db` doesn't roll this back the way plain `db` would).
    """
    executor = MigrationExecutor(connection)
    executor.migrate([("bazos", "0026_addelivery")])
    state = executor.loader.project_state(("bazos", "0026_addelivery"))
    try:
        yield state.apps
    finally:
        call_command("migrate", verbosity=0)


def migrate_to_0027():
    call_command("migrate", "bazos", "0027_merge_duplicate_ads", verbosity=0)


def _canonical_pk(external_id=111):
    """`.values_list`, not `.get()`: a plain `Ad.objects.get()` SELECTs every field
    currently defined on the live model (e.g. `price`/`price_type` from migration 0032),
    and the physical table here is frozen at 0027's schema, which predates them.
    """
    return Ad.objects.filter(marketplace="bazos", external_id=external_id).values_list("pk", flat=True).get()


@pytest.mark.django_db
def test_duplicates_merged_to_one(old_state):
    query, _ = _old_fixtures(old_state)
    _old_ad(old_state, query, 111)
    _old_ad(old_state, query, 111)
    _old_ad(old_state, query, 111)

    migrate_to_0027()

    assert Ad.objects.filter(marketplace="bazos", external_id=111).count() == 1


@pytest.mark.django_db
def test_canonical_is_the_lowest_pk(old_state):
    query, _ = _old_fixtures(old_state)
    first = _old_ad(old_state, query, 111)
    _old_ad(old_state, query, 111)

    migrate_to_0027()

    assert _canonical_pk() == first.pk


@pytest.mark.django_db
def test_deliveries_repointed_to_canonical(old_state):
    query, other_query = _old_fixtures(old_state)
    _old_ad(old_state, query, 111)
    second = _old_ad(old_state, query, 111)
    delivery_on_dup = _old_delivery(old_state, second, other_query)

    migrate_to_0027()

    delivery = AdDelivery.objects.get(pk=delivery_on_dup.pk)
    assert delivery.ad_id == _canonical_pk()


@pytest.mark.django_db
def test_price_history_repointed_to_canonical(old_state):
    query, _ = _old_fixtures(old_state)
    _old_ad(old_state, query, 111)
    second = _old_ad(old_state, query, 111)
    change = _old_price_change(old_state, second, "1000 Kč", "900 Kč")

    migrate_to_0027()

    persisted_change_ad_id = PriceChange.objects.filter(pk=change.pk).values_list("ad_id", flat=True).get()
    assert persisted_change_ad_id == _canonical_pk()


@pytest.mark.django_db
def test_delivery_collision_keeps_lowest_pk_and_deletes_the_other(old_state):
    """Both duplicate Ad rows have a delivery for the *same* query — repointing both would
    violate unique_delivery_per_ad_query. The lower-pk delivery survives."""
    query, other_query = _old_fixtures(old_state)
    first = _old_ad(old_state, query, 111)
    second = _old_ad(old_state, query, 111)

    delivery_on_canonical = _old_delivery(old_state, first, other_query)
    delivery_on_dup = _old_delivery(old_state, second, other_query)

    migrate_to_0027()

    canonical_pk = _canonical_pk()
    assert AdDelivery.objects.filter(ad=canonical_pk, query=other_query.pk).count() == 1
    survivor = AdDelivery.objects.get(ad=canonical_pk, query=other_query.pk)
    assert survivor.pk == min(delivery_on_canonical.pk, delivery_on_dup.pk)


@pytest.mark.django_db
def test_delivery_collision_prefers_sent_over_pending_regardless_of_pk(old_state):
    """A SENT delivery must survive a collision with a PENDING one even when the PENDING
    delivery happens to have the lower pk — losing a SENT delivery to raw pk order would
    silently re-announce an already-delivered ad once the surviving PENDING delivery flows
    back through run_filter/run_sender.
    """
    query, other_query = _old_fixtures(old_state)
    first = _old_ad(old_state, query, 111)
    second = _old_ad(old_state, query, 111)

    # Lower pk, but PENDING — must lose despite being created first.
    pending_delivery = _old_delivery(old_state, first, other_query, status="PENDING")
    # Higher pk, but SENT — must survive.
    sent_delivery = _old_delivery(old_state, second, other_query, status="SENT")
    assert pending_delivery.pk < sent_delivery.pk

    migrate_to_0027()

    survivor = AdDelivery.objects.get(ad=_canonical_pk(), query=other_query.pk)
    assert survivor.pk == sent_delivery.pk
    assert survivor.status == "SENT"


@pytest.mark.django_db
def test_groups_with_differing_price_are_merged_without_error(old_state):
    """Accepted consequence, not solved here: the canonical row's price_raw may be staler
    than a duplicate's. The merge must not crash or try to reconcile it."""
    query, _ = _old_fixtures(old_state)
    _old_ad(old_state, query, 111, price_raw="1000 Kč")
    _old_ad(old_state, query, 111, price_raw="900 Kč")

    migrate_to_0027()

    canonical_price_raw = Ad.objects.filter(marketplace="bazos", external_id=111).values_list("price_raw", flat=True).get()
    assert canonical_price_raw == "1000 Kč"  # unchanged — the canonical row's own facts stand


@pytest.mark.django_db
def test_non_duplicate_ads_are_left_alone(old_state):
    query, _ = _old_fixtures(old_state)
    solo = _old_ad(old_state, query, 999)

    migrate_to_0027()

    assert Ad.objects.filter(pk=solo.pk).exists()
    assert Ad.objects.count() == 1


@pytest.mark.django_db
def test_is_idempotent(old_state):
    query, _ = _old_fixtures(old_state)
    _old_ad(old_state, query, 111)
    _old_ad(old_state, query, 111)

    migrate_to_0027()
    migrate_to_0027()  # re-running an already-applied migration is a no-op via Django,
    # but call the RunPython function again directly to prove the merge logic itself
    # tolerates a clean (already-merged) state.
    import importlib
    migration = importlib.import_module("marketplace.migrations.0027_merge_duplicate_ads")

    class _StubApps:
        def get_model(self, app_label, model_name):
            return {"Ad": Ad, "AdDelivery": AdDelivery, "PriceChange": PriceChange}[model_name]

    migration.merge_duplicate_ads(_StubApps(), schema_editor=None)

    assert Ad.objects.filter(marketplace="bazos", external_id=111).count() == 1


@pytest.mark.django_db
def test_reverse_is_a_noop(old_state):
    """Rolling 0027 back does not resurrect the merged-away duplicate."""
    query, _ = _old_fixtures(old_state)
    _old_ad(old_state, query, 111)
    _old_ad(old_state, query, 111)

    migrate_to_0027()
    assert Ad.objects.filter(marketplace="bazos", external_id=111).count() == 1

    call_command("migrate", "bazos", "0026_addelivery", verbosity=0)

    assert Ad.objects.filter(marketplace="bazos", external_id=111).count() == 1


@pytest.mark.django_db
def test_constraint_rejects_a_new_duplicate_afterwards(query, make_ad):
    """Live-schema test (no old_state needed): confirms the migration's AddConstraint
    actually took on the current, fully-migrated database."""
    make_ad(query, bazos_id=111).save()

    with pytest.raises(IntegrityError):
        make_ad(query, bazos_id=111).save()
