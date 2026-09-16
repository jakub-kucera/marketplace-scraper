"""Provider selection — the same env-string-selects-a-transport shape as `IP_CHANGER_TYPE`."""
import pytest
from django.test import override_settings

from llm.providers.null import NullProvider
from llm.registry import PROVIDER_REGISTRY, LLMProviderName, get_provider


def test_null_is_registered():
    assert LLMProviderName.NULL in PROVIDER_REGISTRY


def test_every_registered_name_is_a_valid_choice():
    """The enum is the single source of valid values, as `Marketplace` is for scrapers."""
    assert set(PROVIDER_REGISTRY) <= set(LLMProviderName.values)


def test_get_provider_defaults_to_the_configured_provider():
    with override_settings(LLM_PROVIDER="NULL"):
        assert isinstance(get_provider(), NullProvider)


def test_get_provider_accepts_an_explicit_name():
    assert isinstance(get_provider("NULL"), NullProvider)


def test_unknown_provider_raises_at_selection_time():
    """Fail loudly on a typo in config rather than silently declining forever."""
    with pytest.raises(ValueError, match="NOPE"):
        get_provider("NOPE")


def test_the_shipped_default_is_null():
    """Shipping inert is the point: no key, no egress, nothing to opt out of.

    Asserts the *declared* fallback rather than the resolved setting — a developer with a
    real provider in their own `.env` must not fail the suite for having configured one.
    """
    import pathlib

    import scraper

    source = (pathlib.Path(scraper.__file__).parent / "settings.py").read_text(encoding="utf-8")
    assert 'env("LLM_PROVIDER", default="NULL")' in source


def test_an_unset_provider_resolves_to_null():
    with override_settings(LLM_PROVIDER=""):
        assert isinstance(get_provider(), NullProvider)


def test_env_sample_ships_the_inert_default():
    """`.env.sample` is what a fresh checkout copies, so it is the real shipped default."""
    import pathlib

    import scraper

    sample = (pathlib.Path(scraper.__file__).parents[1] / ".env.sample").read_text(encoding="utf-8")
    assert "LLM_PROVIDER=NULL" in sample
