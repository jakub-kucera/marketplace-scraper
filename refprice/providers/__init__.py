"""Reference-price providers, and the import that makes them exist.

`ZboziProvider` registers itself with a `@register` decorator, which runs only when its
module is imported. Nothing in production code did: `get_provider("zbozi")` raised
`Unknown reference provider 'zbozi'. Implemented: []` in any process that had not imported
it by hand, which meant the admin action and `manage.py lookup_reference_price` had both
been dead since the app shipped. The tests did not catch it because a test importing
`ZboziProvider` to build one *is* the missing import.

So the package imports its implementations, and importing `refprice.providers` — which
`base` and `services` both pull in — is what populates the registry. Same job
`_build_scrapers` does by listing every scraper explicitly: a registry whose contents depend
on who imported what is not a registry.

Add a provider here when you add one; `test_registry_is_populated_by_importing_the_package`
fails if you forget.
"""
from refprice.providers.base import (  # noqa: F401
    PROVIDER_REGISTRY,
    ReferenceProvider,
    get_provider,
    register,
)
from refprice.providers.zbozi import ZboziProvider  # noqa: F401  — imported for its @register side effect

__all__ = ["PROVIDER_REGISTRY", "ReferenceProvider", "ZboziProvider", "get_provider", "register"]
