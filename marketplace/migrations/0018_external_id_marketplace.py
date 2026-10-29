from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("bazos", "0017_ad_status_suppressed"),
    ]

    operations = [
        # Rename bazos_id → external_id on Ad.
        # Django handles this as a column rename (no data loss).
        migrations.RenameField(
            model_name="ad",
            old_name="bazos_id",
            new_name="external_id",
        ),
        # Add marketplace field to Ad.
        # All existing rows are Bazos ads, so default="bazos" is correct.
        migrations.AddField(
            model_name="ad",
            name="marketplace",
            field=models.CharField(default="bazos", max_length=20, db_index=True),
        ),
        # Add marketplace field to Query.
        migrations.AddField(
            model_name="query",
            name="marketplace",
            field=models.CharField(default="bazos", max_length=20),
        ),
    ]
