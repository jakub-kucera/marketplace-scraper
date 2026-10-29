"""The migration chain must build on SQLite, because the weekly live contract check runs on
it (`TEST_DB=sqlite`, see conftest.py) and builds the schema before any live test can run.

Regression: 0052 used `DROP COLUMN IF EXISTS`, which SQLite does not parse, and every Bazos
contract test errored at setup from 2026-10-05 to 10-26 - four weeks with the drift check
blind. The rest of the suite runs on Postgres and could not notice; this runs in a
subprocess because the session's database is already Postgres by the time a test starts.
"""
import subprocess
import sys

MIGRATE_ON_SQLITE = """
import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "scraper.settings")
from django.conf import settings
settings.DATABASES["default"] = {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}
import django
django.setup()
from django.core.management import call_command
call_command("migrate", verbosity=0)
"""


def test_every_migration_applies_on_sqlite():
    result = subprocess.run(
        [sys.executable, "-c", MIGRATE_ON_SQLITE], capture_output=True, text=True, timeout=300
    )
    assert result.returncode == 0, result.stderr[-1500:]
