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


def test_default_settings_choose_null():
    """Shipping inert is the point: no key, no egress, nothing to opt out of."""
    from django.conf import settings
    assert settings.LLM_PROVIDER == "NULL"
