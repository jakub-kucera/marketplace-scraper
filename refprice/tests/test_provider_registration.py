"""The registry has to be populated by importing the package, not by luck.

This whole app was dead on arrival and the suite did not notice. `ZboziProvider` registers
itself with a decorator that runs on import, nothing in production code imported the module,
and every test that exercised the provider imported it to build one — so the act of testing
supplied the missing import. `manage.py lookup_reference_price` and the admin action both
raised `Unknown reference provider 'zbozi'. Implemented: []` in a real process, from the day
the app shipped until 2026-09-17, when running the job for the first time surfaced it.

Nothing in this module may import `refprice.providers.zbozi`. That is the point.
"""
import subprocess
import sys

import pytest


def test_registry_is_populated_by_importing_the_package():
    from refprice.providers import PROVIDER_REGISTRY

    assert "zbozi" in PROVIDER_REGISTRY


def test_get_provider_works_for_a_caller_that_only_imported_services():
    """The path every real caller takes: the admin action, the management command and the
    job all reach the provider through `refprice.services`, never by importing it."""
    from refprice.services import get_provider

    assert get_provider("zbozi") is not None


@pytest.mark.parametrize("entry_point", [
    "from refprice.services import lookup_reference_price; from refprice.providers.base import get_provider; get_provider('zbozi')",
    "from refprice.providers.base import get_provider; get_provider('zbozi')",
    "import refprice.jobs; from refprice.providers.base import get_provider; get_provider('zbozi')",
])
def test_a_fresh_interpreter_can_resolve_the_provider(entry_point):
    """In-process tests cannot prove this: by the time one runs, some *other* test has
    almost certainly imported the module already. A subprocess is the only honest check that
    a cold worker — which is what django-q2 gives a task — can resolve a provider.
    """
    code = (
        "import django, os; "
        "os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'scraper.settings'); "
        "django.setup(); " + entry_point
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, timeout=120
    )
    assert result.returncode == 0, result.stderr[-1500:]
