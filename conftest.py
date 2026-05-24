import pytest


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
