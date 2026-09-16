"""Response caching — identical input must not be billed twice.

Scope worth being honest about: this is Django's cache framework, which in the default
locmem configuration is per-process and dies with the process. It dedupes within a run,
which is where the repeats actually cluster — `refprice` normalises many scruffy ad titles
down to the same `brand + line + model code` before anything reaches a model. Durable
amortisation across restarts comes from persisting the *match* (`RefProductLink`), not
from this cache.

A cached hit still writes an `LLMCall` row, flagged `cached`. Dropping it would make the
audit log answer "how often was this asked" incorrectly.
"""
from dataclasses import dataclass

import pytest
from django.core.cache import cache
from django.test import override_settings

from llm import services
from llm.base import LLMResult
from llm.models import LLMCall

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class Pick:
    index: int


@dataclass(frozen=True)
class Other:
    """Same field shape as Pick, different type — module level because a cached value
    goes through pickle, and a class defined inside a test function cannot."""
    index: int


class CountingProvider:
    name = "FAKE"

    def __init__(self, raw='{"index": 1}'):
        self.raw, self.calls = raw, 0

    def complete(self, *, prompt, system, schema, max_output_tokens, temperature):
        self.calls += 1
        from llm.base import parse_into
        value, reason = parse_into(schema, self.raw)
        return LLMResult(value=value, raw=self.raw, provider=self.name, model="fake-1",
                         tokens_in=10, tokens_out=2, cost_usd=0.001, latency_ms=5,
                         declined_reason=reason)


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()


def call(provider, **over):
    kwargs = dict(prompt="same question", schema=Pick, prompt_name="p",
                  prompt_version="v1", provider=provider)
    kwargs.update(over)
    return services.complete(**kwargs)


# ---------------------------------------------------------------------------

def test_a_repeat_call_does_not_reach_the_provider():
    p = CountingProvider()
    call(p)
    call(p)
    assert p.calls == 1


def test_a_repeat_call_returns_the_same_value():
    p = CountingProvider()
    assert call(p).value == call(p).value == Pick(1)


def test_the_second_result_is_flagged_cached():
    p = CountingProvider()
    call(p)
    assert call(p).cached is True


def test_the_first_result_is_not_flagged_cached():
    assert call(CountingProvider()).cached is False


def test_a_cached_hit_still_writes_an_audit_row():
    p = CountingProvider()
    call(p)
    call(p)
    assert LLMCall.objects.count() == 2
    assert LLMCall.objects.filter(cached=True).count() == 1


def test_a_cached_hit_is_billed_zero():
    """The money was spent once. Counting it twice would close the budget early."""
    p = CountingProvider()
    call(p)
    call(p)
    cached_row = LLMCall.objects.get(cached=True)
    assert float(cached_row.cost_usd) == 0.0


def test_a_different_prompt_is_a_different_key():
    p = CountingProvider()
    call(p, prompt="one")
    call(p, prompt="two")
    assert p.calls == 2


def test_a_different_prompt_version_is_a_different_key():
    """The whole point of versioning prompts is that v2 may answer differently."""
    p = CountingProvider()
    call(p, prompt_version="v1")
    call(p, prompt_version="v2")
    assert p.calls == 2


def test_a_different_model_is_a_different_key():
    p = CountingProvider()
    with override_settings(LLM_MODEL="model-a"):
        call(p)
    with override_settings(LLM_MODEL="model-b"):
        call(p)
    assert p.calls == 2


def test_declines_are_not_cached():
    """A refusal is often transient; caching it would freeze a bad answer in place."""
    p = CountingProvider(raw="no thanks")
    call(p)
    call(p)
    assert p.calls == 2


def test_a_different_schema_is_a_different_key():
    """The cached object is an instance of the schema — sharing a key across two
    dataclasses would hand the caller the wrong type, not merely a stale answer."""
    p = CountingProvider()
    first = call(p, schema=Pick)
    second = call(p, schema=Other)
    assert p.calls == 2
    assert type(first.value) is Pick
    assert type(second.value) is Other


@override_settings(LLM_CACHE_SECONDS=0)
def test_caching_can_be_switched_off():
    p = CountingProvider()
    call(p)
    call(p)
    assert p.calls == 2
