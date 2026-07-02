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
def django_db_setup(django_test_environment, django_db_blocker):
    from django.conf import settings
    from django.db import connections
    from django.test.utils import setup_databases, teardown_databases

    # Update in-place to preserve defaults (TEST key etc.) that configure_settings()
    # already populated in this dict; replacing the dict would lose them.
    settings.DATABASES["default"].update({
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
        "OPTIONS": {},  # clear PostgreSQL-specific options (e.g. connect_timeout)
    })
    # Drop the cached connection so it is recreated with the new ENGINE on next access.
    del connections["default"]

    with django_db_blocker.unblock():
        old_config = setup_databases(verbosity=0, interactive=False)
    yield
    with django_db_blocker.unblock():
        teardown_databases(old_config, verbosity=0)
