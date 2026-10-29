"""Tests for migration 0033_backfill_price.

Same approach as test_sentinel_publisher_migration.py: `apps.get_model` is stubbed with the
real model classes and the migration's `backfill_price` function is called directly, since
the migration only touches fields present in both the historical and current model state.
"""
import importlib

import pytest

from marketplace.models import Ad, PriceChange, PriceType

migration = importlib.import_module("marketplace.migrations.0033_backfill_price")


class _StubApps:
    _models = {"Ad": Ad, "PriceChange": PriceChange}

    def get_model(self, app_label, model_name):
        assert app_label == "bazos"
        return self._models[model_name]


def run_migration():
    migration.backfill_price(_StubApps(), schema_editor=None)


@pytest.mark.django_db
def test_backfills_exact_price(query, make_ad):
    ad = make_ad(query, bazos_id=1)
    ad.price_raw = "1 000 Kč"
    ad.save()

    run_migration()

    ad.refresh_from_db()
    assert ad.price == 1000
    assert ad.price_type == PriceType.EXACT


@pytest.mark.django_db
def test_backfills_free_as_zero_not_null(query, make_ad):
    ad = make_ad(query, bazos_id=2)
    ad.price_raw = "Zdarma"
    ad.save()

    run_migration()

    ad.refresh_from_db()
    assert ad.price == 0
    assert ad.price_type == PriceType.FREE


@pytest.mark.django_db
def test_backfills_indifferent_placeholder(query, make_ad):
    """Nerozhoduje — missing from P22's original enum, added per the corpus measurement."""
    ad = make_ad(query, bazos_id=3)
    ad.price_raw = "Nerozhoduje"
    ad.save()

    run_migration()

    ad.refresh_from_db()
    assert ad.price is None
    assert ad.price_type == PriceType.INDIFFERENT


@pytest.mark.django_db
def test_backfills_unrecognised_string_as_unknown(query, make_ad):
    ad = make_ad(query, bazos_id=4)
    ad.price_raw = "Za rozumnou cenu"
    ad.save()

    run_migration()

    ad.refresh_from_db()
    assert ad.price is None
    assert ad.price_type == PriceType.UNKNOWN


@pytest.mark.django_db
def test_backfills_price_change_amounts(query, make_ad):
    ad = make_ad(query, bazos_id=5)
    ad.save()
    PriceChange.objects.create(ad=ad, old_price="1 000 Kč", new_price="800 Kč")

    run_migration()

    change = PriceChange.objects.get(ad=ad)
    assert change.old_price_amount == 1000
    assert change.new_price_amount == 800


@pytest.mark.django_db
def test_is_idempotent(query, make_ad):
    ad = make_ad(query, bazos_id=6)
    ad.price_raw = "500 Kč"
    ad.save()

    run_migration()
    run_migration()

    ad.refresh_from_db()
    assert ad.price == 500
    assert ad.price_type == PriceType.EXACT
