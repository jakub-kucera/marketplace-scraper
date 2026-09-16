"""Live contract check against the real Gemini API. Deselected by default (`-m live`).

Skips itself when no key is configured, so it is inert on CI and on a fresh checkout —
the same posture as the provider itself.

What it guards is narrow and deliberate: that the **request shape still works and the
response still parses**. It does not assert what the model says. A model that answers
differently is not a contract break; a model that stops honouring `responseSchema`, or a
`generateContent` URL that starts 404ing, is — and that is what would otherwise surface
as "the LLM rung quietly declines everything".

Run:  pytest -m live llm/tests/test_gemini_contract.py
"""
from dataclasses import dataclass

import pytest
from django.conf import settings
from django.test import override_settings

from llm.providers.gemini import DEFAULT_MODEL, GeminiProvider

pytestmark = pytest.mark.live


@dataclass(frozen=True)
class Ping:
    answer: str
    confidence: float
    count: int


@pytest.fixture(scope="module")
def provider():
    if not (getattr(settings, "GEMINI_API_KEY", "") or settings.LLM_API_KEY):
        pytest.skip("no Gemini API key configured")
    with override_settings(LLM_MODEL=DEFAULT_MODEL):
        yield GeminiProvider()


@pytest.fixture(scope="module")
def answer(provider):
    result = provider.complete(
        prompt='Reply with answer "pong", confidence 1.0, and count 3.',
        system="You answer only with JSON.",
        schema=Ping,
        max_output_tokens=200,
        temperature=0.0,
    )
    if result.declined:
        pytest.fail(f"live call declined: {result.declined_reason} (raw={result.raw[:200]!r})")
    return result


def test_the_default_model_still_exists(answer):
    """`gemini-2.5-flash-lite` was listed by the models endpoint and still 404'd on
    generateContent, so the model list is not proof a model is callable."""
    assert answer.value is not None


def test_response_schema_is_still_honoured(answer):
    """The whole reliability argument for this provider. If Gemini stops constraining the
    output, `parse_into` becomes a gamble again and declines climb silently."""
    assert isinstance(answer.value, Ping)
    assert answer.value.answer


def test_schema_types_survive_the_round_trip(answer):
    assert isinstance(answer.value.confidence, float)
    assert isinstance(answer.value.count, int)


def test_usage_metadata_is_still_reported(answer):
    """Token counts feed the budget ceiling. Losing them silently uncaps spend."""
    assert answer.tokens_in > 0
    assert answer.tokens_out > 0


def test_the_models_endpoint_still_lists_the_default(provider):
    models = provider.list_models()
    assert models, "models endpoint returned nothing"
    assert DEFAULT_MODEL in models, (
        f"{DEFAULT_MODEL} is gone from the model list — pick a new gemini.DEFAULT_MODEL"
    )


def test_a_bad_model_name_declines_rather_than_raising(provider):
    with override_settings(LLM_MODEL="gemini-definitely-not-a-model"):
        result = GeminiProvider().complete(
            prompt="hi", system=None, schema=Ping, max_output_tokens=50, temperature=0.0,
        )
    assert result.declined is True
    assert result.declined_reason is not None and "404" in result.declined_reason
