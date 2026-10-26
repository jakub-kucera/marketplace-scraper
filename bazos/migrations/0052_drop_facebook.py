from django.db import migrations


def drop_facebook(apps, schema_editor):
    """Remove the facebook app's schema. Hand-written SQL because 0005 and 0012 were edited to
    never create it, so the migration state has nothing left to generate a RemoveField from -
    only databases migrated before that edit (production) still carry the column and table.
    The column is looked up rather than dropped with IF EXISTS, which SQLite does not parse -
    and the weekly contract check builds its schema on SQLite."""
    connection = schema_editor.connection
    with connection.cursor() as cursor:
        columns = {c.name for c in connection.introspection.get_table_description(cursor, "bazos_phonepublisher")}
    if "fb_user_id" in columns:
        schema_editor.execute("ALTER TABLE bazos_phonepublisher DROP COLUMN fb_user_id")
    schema_editor.execute("DROP TABLE IF EXISTS facebook_fbuser")
    schema_editor.execute("DELETE FROM django_migrations WHERE app = 'facebook'")


class Migration(migrations.Migration):

    dependencies = [
        ("bazos", "0051_sellerreview"),
    ]

    operations = [
        migrations.RunPython(drop_facebook, migrations.RunPython.noop),
    ]
