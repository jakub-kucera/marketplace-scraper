"""Provider selection by name — the Protocol-plus-registry pattern, fourth instance.

`MarketplaceScraper`/`_build_scrapers`, `RULE_REGISTRY` and `MODEL_REGISTRY` are the other
three. As with `Marketplace`, the `TextChoices` enum is the single source of valid values
rather than free-text strings scattered through settings.
"""
from django.conf import settings
from django.db import models

from llm.base import LLMProvider
from llm.providers.anthropic import AnthropicProvider
from llm.providers.null import NullProvider


class LLMProviderName(models.TextChoices):
    NULL = "NULL", "None (declines every call)"
    ANTHROPIC = "ANTHROPIC", "Anthropic"
    OPENAI = "OPENAI", "OpenAI"
    OPENROUTER = "OPENROUTER", "OpenRouter"
    OLLAMA = "OLLAMA", "Ollama (local)"


#: Only backends that are actually implemented appear here. A name in `LLMProviderName`
#: with no entry is a planned provider, and asking for it fails loudly at selection time.
PROVIDER_REGISTRY: dict[str, type] = {
    LLMProviderName.NULL: NullProvider,
    LLMProviderName.ANTHROPIC: AnthropicProvider,
}


def get_provider(name: str | None = None) -> LLMProvider:
    """Resolve a provider, defaulting to `settings.LLM_PROVIDER`.

    Raises on an unknown name rather than falling back to NULL: a typo in `.env` that
    silently declined every call for a month is indistinguishable from a model that
    never has an opinion.
    """
    name = (name or settings.LLM_PROVIDER or LLMProviderName.NULL).upper()
    try:
        return PROVIDER_REGISTRY[name]()
    except KeyError:
        raise ValueError(
            f"Unknown LLM provider {name!r}. Implemented: {sorted(PROVIDER_REGISTRY)}"
        ) from None
