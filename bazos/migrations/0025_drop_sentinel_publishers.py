"""Detach and remove the ``bazos_id=0`` sentinel publisher rows.

A ``0`` publisher id is Bazos's "this ad has no publisher of that kind" marker, not an
identity. It was previously stored as a real ``EmailPublisher``/``PhonePublisher`` row via
``get_or_create``, so every ad lacking an email publisher pointed at the *same* row.

Measured on the 2024-03 export (16,987 ads): a single ``EmailPublisher`` with
``bazos_id=0`` held **1,137 ads (6.7%) across 671 distinct phone publishers**, and acted as
a hub merging **8.3% of all ads** into one connected component when grouping sellers by
shared identity. Excluding it drops the largest component from 1,408 ads to 369.

The scraper now writes NULL instead (``BazosScraper._resolve_publishers``); this migration
fixes the rows already in the database. Both FKs are ``on_delete=PROTECT``, so the ads must
be detached before the sentinel rows can be deleted.
"""

from django.db import migrations


def drop_sentinel_publishers(apps, schema_editor):
    Ad = apps.get_model("bazos", "Ad")
    EmailPublisher = apps.get_model("bazos", "EmailPublisher")
    PhonePublisher = apps.get_model("bazos", "PhonePublisher")

    for model, field in ((EmailPublisher, "email_publisher"), (PhonePublisher, "phone_publisher")):
        for sentinel in model.objects.filter(bazos_id=0):
            Ad.objects.filter(**{field: sentinel}).update(**{field: None})
            sentinel.delete()


def noop_reverse(apps, schema_editor):
    """Irreversible in substance, permitted in form.

    The sentinel rows carried no information beyond "absent", so re-creating them would
    invent data rather than restore it. Left as a no-op so the migration can be unapplied
    without blocking a rollback of later migrations.
    """


class Migration(migrations.Migration):

    dependencies = [
        ("bazos", "0024_alter_ad_marketplace_alter_query_marketplace"),
    ]

    operations = [
        migrations.RunPython(drop_sentinel_publishers, noop_reverse),
    ]
