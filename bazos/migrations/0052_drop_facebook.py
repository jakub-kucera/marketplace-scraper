from django.db import migrations


def drop_facebook(apps, schema_editor):
    """Remove the facebook app's schema. Hand-written SQL because 0005 and 0012 were edited to
    never create it, so the migration state has nothing left to generate a RemoveField from -
    only databases migrated before that edit (production) still carry the column and table."""
    schema_editor.execute("ALTER TABLE bazos_phonepublisher DROP COLUMN IF EXISTS fb_user_id")
    schema_editor.execute("DROP TABLE IF EXISTS facebook_fbuser")
    schema_editor.execute("DELETE FROM django_migrations WHERE app = 'facebook'")


class Migration(migrations.Migration):

    dependencies = [
        ("bazos", "0051_sellerreview"),
    ]

    operations = [
        migrations.RunPython(drop_facebook, migrations.RunPython.noop),
    ]
