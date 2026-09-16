"""The Anthropic provider — request shape, cost accounting, and the retry budget.

It talks to the Messages API with `requests` rather than the vendor SDK. That is the same
call `bazos/pricing` makes when it evaluates a linear model with a dot product instead of
adding numpy to an ARM64 Pi image: one endpoint does not justify a dependency, and
`requests` is already here.

Nothing in this file touches the network.
"""
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.test import override_settings

from llm.providers.anthropic import PRICING, AnthropicProvider


@dataclass(frozen=True)
class Pick:
    index: int
    reason: str


def response(status=200, *, text='{"index": 1, "reason": "ok"}', tokens=(100, 20),
             stop_reason="end_turn"):
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.json.return_value = {
        "content": [{"type": "text", "text": text}],
        "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]},
        "stop_reason": stop_reason,
        "model": "claude-haiku-4-5-20251001",
    }
    r.text = text
    return r


@pytest.fixture()
def provider():
    with override_settings(LLM_API_KEY="sk-test", LLM_MODEL="claude-haiku-4-5-20251001"):
        yield AnthropicProvider()


def run(provider, resp, schema=Pick):
    """Call the provider with `requests.post` stubbed to return `resp` (or a sequence)."""
    with patch("llm.providers.anthropic.requests.post") as post, \
         patch("llm.providers.anthropic.time.sleep"):
        post.side_effect = resp if isinstance(resp, list) else [resp]
        result = provider.complete(prompt="pick", system="be terse", schema=schema,
                                   max_output_tokens=256, temperature=0.0)
    return result, post


# ---------------------------------------------------------------------------
# the request it builds
# ---------------------------------------------------------------------------

def test_posts_to_the_messages_endpoint(provider):
    _, post = run(provider, response())
    assert post.call_args.args[0] == "https://api.anthropic.com/v1/messages"


def test_sends_the_api_key_and_version_headers(provider):
    _, post = run(provider, response())
    headers = post.call_args.kwargs["headers"]
    assert headers["x-api-key"] == "sk-test"
    assert headers["anthropic-version"]


def test_sends_model_max_tokens_temperature_and_system(provider):
    _, post = run(provider, response())
    body = post.call_args.kwargs["json"]
    assert body["model"] == "claude-haiku-4-5-20251001"
    assert body["max_tokens"] == 256
    assert body["temperature"] == 0.0
    assert body["system"] == "be terse"
    assert body["messages"] == [{"role": "user", "content": "pick"}]


def test_omits_system_when_none(provider):
    with patch("llm.providers.anthropic.requests.post") as post, \
         patch("llm.providers.anthropic.time.sleep"):
        post.return_value = response()
        provider.complete(prompt="p", system=None, schema=Pick,
                          max_output_tokens=64, temperature=0.0)
    assert "system" not in post.call_args.kwargs["json"]


def test_sends_a_timeout(provider):
    """Through any transport an unreachable host is a stalled socket, not a refusal."""
    _, post = run(provider, response())
    assert post.call_args.kwargs["timeout"]


# ---------------------------------------------------------------------------
# the answer it returns
# ---------------------------------------------------------------------------

def test_parses_the_value(provider):
    result, _ = run(provider, response())
    assert result.value == Pick(1, "ok")


def test_records_token_counts(provider):
    result, _ = run(provider, response(tokens=(310, 42)))
    assert (result.tokens_in, result.tokens_out) == (310, 42)


def test_computes_cost_from_the_pricing_table(provider):
    in_rate, out_rate = PRICING["claude-haiku-4-5-20251001"]
    result, _ = run(provider, response(tokens=(1_000_000, 1_000_000)))
    assert result.cost_usd == pytest.approx(in_rate + out_rate)


def test_an_unknown_model_costs_zero_and_says_so(provider):
    """Better a visibly wrong zero than a silently invented price."""
    with override_settings(LLM_MODEL="claude-future-9"):
        p = AnthropicProvider()
        result, _ = run(p, response(tokens=(500, 50)))
    assert result.cost_usd == 0.0


def test_keeps_the_raw_text_even_on_success(provider):
    result, _ = run(provider, response(text='{"index": 2, "reason": "y"}'))
    assert result.raw == '{"index": 2, "reason": "y"}'


def test_unparseable_output_declines(provider):
    result, _ = run(provider, response(text="I cannot help with that."))
    assert result.declined is True
    assert result.raw == "I cannot help with that."


def test_a_truncated_answer_declines_and_names_the_stop_reason(provider):
    result, _ = run(provider, response(text='{"index": 1, "reas',
                                       stop_reason="max_tokens"))
    assert result.declined is True
    assert "max_tokens" in result.declined_reason


def test_schema_none_returns_prose(provider):
    result, _ = run(provider, response(text="just words"), schema=None)
    assert result.value == "just words"


# ---------------------------------------------------------------------------
# retries — only on 429/5xx, and never forever
# ---------------------------------------------------------------------------

def test_retries_a_429_then_succeeds(provider):
    result, post = run(provider, [response(429), response()])
    assert post.call_count == 2
    assert result.value == Pick(1, "ok")


def test_retries_a_500_then_succeeds(provider):
    result, post = run(provider, [response(503), response()])
    assert post.call_count == 2
    assert result.declined is False


def test_gives_up_after_the_retry_budget_and_declines(provider):
    result, post = run(provider, [response(429)] * 10)
    assert post.call_count <= 4
    assert result.declined is True
    assert "429" in result.declined_reason


def test_does_not_retry_a_400(provider):
    """A bad request will be bad the second time too; retrying just spends the budget."""
    result, post = run(provider, [response(400), response()])
    assert post.call_count == 1
    assert result.declined is True


def test_does_not_retry_a_401(provider):
    result, post = run(provider, [response(401), response()])
    assert post.call_count == 1
    assert result.declined is True


def test_a_transport_exception_declines_rather_than_raising(provider):
    result, post = run(provider, [requests.ConnectionError("no route")] * 10)
    assert result.declined is True
    assert "no route" in result.declined_reason


def test_a_missing_api_key_declines_without_calling_out(provider):
    with override_settings(LLM_API_KEY=""):
        p = AnthropicProvider()
        with patch("llm.providers.anthropic.requests.post") as post:
            result = p.complete(prompt="x", system=None, schema=Pick,
                                max_output_tokens=64, temperature=0.0)
    assert result.declined is True
    assert post.call_count == 0


def test_satisfies_the_provider_protocol(provider):
    from llm.base import LLMProvider
    assert isinstance(provider, LLMProvider)


def test_is_registered_under_its_name():
    from llm.registry import PROVIDER_REGISTRY, LLMProviderName
    assert PROVIDER_REGISTRY[LLMProviderName.ANTHROPIC] is AnthropicProvider
