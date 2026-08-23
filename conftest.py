import os

import pytest


@pytest.fixture(autouse=True, scope="session")
def disable_db_log_handler():
    """No-op DatabaseLogHandler.emit for the whole test session.

    ``DatabaseLogHandler`` writes every log record to the DB. Pure unit tests
    don't have DB access, so any logger.* call inside them raises
    ``RuntimeError: Database access not allowed``.

    Patching ``emit`` to a no-op is the minimal, reliable fix: it fires before
    Django's lazy logger configuration, survives handler re-registration, and
    doesn't affect any other part of the logging chain.
    """
    try:
        from django_db_logger.db_log_handler import DatabaseLogHandler
        DatabaseLogHandler.emit = lambda self, record: None
    except ImportError:
        pass
    yield


@pytest.fixture(scope="session")
def django_db_modify_db_settings(django_db_modify_db_settings_parallel_suffix):
    """Build the test database. PostgreSQL by default; SQLite only on request.

    The suite runs against a real PostgreSQL server — the same engine as production — so
    that Postgres-only behaviour is actually exercised: ``select_for_update(skip_locked=True,
    of=("self",))`` in run_filter/run_sender (SQLite's backend has ``has_select_for_update =
    False`` and silently drops it from the SQL), the deferred-FK-trigger flush in migration
    0027, and the column/integer width limits SQLite does not enforce at all.

    Locally this needs `docker compose up -d postgres`. Connection settings come from `.env`
    via settings.py, and Django builds an isolated `test_<POSTGRES_DB>` database — the dev
    database itself is never touched.

    ``TEST_DB=sqlite`` swaps in an in-memory SQLite database instead. That exists for exactly
    one caller: the weekly live contract check (.github/workflows/contract-check.yml), which
    runs `pytest -m live` in a throwaway container on the Pi with no database to reach. Those
    tests assert on live-site parsing, not on database behaviour, so the backend is irrelevant
    to what they check. Don't reach for it to make a failing test pass — a test that fails on
    Postgres and passes on SQLite is reporting a real defect.

    This is ``django_db_modify_db_settings``, not ``django_db_setup``: it mutates DATABASES
    before pytest-django builds the database, instead of replacing the fixture that does the
    building. Overriding ``django_db_setup`` would forfeit ``--reuse-db``/``--create-db``,
    which live inside it — and on Postgres those are worth keeping, because the ~40-migration
    chain now dominates a run (54s → 28s on a reused database).

    One caveat that comes with ``--reuse-db``: the migration tests
    (test_merge_duplicate_ads_migration.py and friends) roll the schema *backwards* to an
    older migration and forward again in a fixture teardown. A run killed mid-test can leave
    a reused database stranded at that older schema; ``--create-db`` rebuilds it. The default
    (no flag) builds a fresh database every run and is immune.
    """
    if os.environ.get("TEST_DB", "").lower() == "sqlite":
        from django.conf import settings
        from django.db import connections

        # Update in-place to preserve defaults (TEST key etc.) that configure_settings()
        # already populated in this dict; replacing the dict would lose them.
        settings.DATABASES["default"].update({
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
            "OPTIONS": {},  # clear PostgreSQL-specific options (e.g. connect_timeout)
        })
        # Drop the cached connection so it is recreated with the new ENGINE on next access.
        del connections["default"]
