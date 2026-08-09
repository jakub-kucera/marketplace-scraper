"""Tests for migration 0025_drop_sentinel_publishers.

The migration is destructive (detaches ads, then deletes publisher rows), so its logic is
exercised directly rather than trusted. `apps.get_model` is stubbed with the real model
classes — the migration only touches fields present in both the historical and current
model state, so they are an adequate stand-in.
"""
import importlib

import pytest

from bazos.models import Ad, EmailPublisher, PhonePublisher

migration = importlib.import_module("bazos.migrations.0025_drop_sentinel_publishers")


class _StubApps:
    """Minimal `apps` shim: resolves the three models the migration asks for."""

    _models = {"Ad": Ad, "EmailPublisher": EmailPublisher, "PhonePublisher": PhonePublisher}

    def get_model(self, app_label, model_name):
        assert app_label == "bazos"
        return self._models[model_name]


def run_migration():
    migration.drop_sentinel_publishers(_StubApps(), schema_editor=None)


@pytest.fixture
def sentinel_email():
    return EmailPublisher.objects.create(bazos_id=0)


@pytest.mark.django_db
def test_detaches_ads_and_deletes_the_sentinel_row(query, make_ad, sentinel_email):
    real_phone_a = PhonePublisher.objects.create(bazos_id=111)
    real_phone_b = PhonePublisher.objects.create(bazos_id=222)
    for bazos_id, phone in ((1, real_phone_a), (2, real_phone_b)):
        ad = make_ad(query, bazos_id)
        ad.email_publisher = sentinel_email
        ad.phone_publisher = phone
        ad.save()

    run_migration()

    assert not EmailPublisher.objects.filter(bazos_id=0).exists()
    assert Ad.objects.count() == 2
    assert list(Ad.objects.values_list("email_publisher", flat=True)) == [None, None]
    # the real publishers on the same ads must survive untouched
    assert set(Ad.objects.values_list("phone_publisher__bazos_id", flat=True)) == {111, 222}


@pytest.mark.django_db
def test_leaves_real_publishers_alone(query, make_ad):
    real_email = EmailPublisher.objects.create(bazos_id=5998423)
    ad = make_ad(query, 1)
    ad.email_publisher = real_email
    ad.save()

    run_migration()

    ad.refresh_from_db()
    assert ad.email_publisher == real_email
    assert EmailPublisher.objects.filter(bazos_id=5998423).exists()


@pytest.mark.django_db
def test_handles_sentinel_on_the_phone_side_too(query, make_ad):
    """No such rows exist in the current export, but the old code path could create them."""
    sentinel_phone = PhonePublisher.objects.create(bazos_id=0)
    ad = make_ad(query, 1)
    ad.phone_publisher = sentinel_phone
    ad.save()

    run_migration()

    ad.refresh_from_db()
    assert ad.phone_publisher is None
    assert not PhonePublisher.objects.filter(bazos_id=0).exists()


@pytest.mark.django_db
def test_is_idempotent_and_safe_on_a_clean_database():
    run_migration()
    run_migration()

    assert not EmailPublisher.objects.filter(bazos_id=0).exists()


@pytest.mark.django_db
def test_reverse_is_a_noop(sentinel_email):
    migration.noop_reverse(_StubApps(), schema_editor=None)

    assert EmailPublisher.objects.filter(bazos_id=0).exists()
