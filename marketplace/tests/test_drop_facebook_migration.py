"""Tests for migration 0052_drop_facebook.

A fresh database never gets the facebook schema - 0005 and 0012 were edited to stop creating
it - so the test suite's own DB cannot show that production's copy is removed. These tests
recreate production's shape by hand and run the migration's function against it.
"""
import importlib

import pytest
from django.db import connection

migration = importlib.import_module("marketplace.migrations.0052_drop_facebook")


def run_migration():
    with connection.schema_editor() as schema_editor:
        migration.drop_facebook(apps=None, schema_editor=schema_editor)


def table_exists(name):
    return name in connection.introspection.table_names()


def column_names(table):
    with connection.cursor() as cursor:
        return {c.name for c in connection.introspection.get_table_description(cursor, table)}


def facebook_migration_rows():
    with connection.cursor() as cursor:
        cursor.execute("SELECT count(*) FROM django_migrations WHERE app = 'facebook'")
        return cursor.fetchone()[0]


@pytest.mark.django_db(transaction=True)
def test_removes_the_production_facebook_schema():
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE facebook_fbuser (id bigserial PRIMARY KEY, facebook_id varchar(30))")
        cursor.execute(
            "ALTER TABLE bazos_phonepublisher ADD COLUMN fb_user_id bigint NULL "
            "REFERENCES facebook_fbuser (id) DEFERRABLE INITIALLY DEFERRED"
        )
        cursor.execute("INSERT INTO django_migrations (app, name, applied) VALUES ('facebook', '0001_initial', now())")

    run_migration()

    assert not table_exists("facebook_fbuser")
    assert "fb_user_id" not in column_names("bazos_phonepublisher")
    assert facebook_migration_rows() == 0


@pytest.mark.django_db(transaction=True)
def test_is_a_no_op_on_a_fresh_database():
    assert not table_exists("facebook_fbuser")

    run_migration()

    assert not table_exists("facebook_fbuser")
    assert "phone" in column_names("bazos_phonepublisher")
