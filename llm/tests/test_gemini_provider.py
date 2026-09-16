"""The Gemini provider — request shape, schema-constrained output, quota handling.

Why this provider exists alongside Anthropic: `LLM_AD_REVIEW.md` §2f already measured that
**a free tier can carry this workload** (~1,500 requests/day, comfortably above a filtered
candidate stream), and that for EEA/UK/CH users Google's paid-tier data terms apply to the
free tier too — so free-tier prompts are not used for training. That is what makes free
viable here rather than merely tempting.

Two things differ from the Anthropic path and both are deliberate:

- **`responseSchema` constrains the output server-side.** The model is handed the dataclass
  shape, so `parse_into` is a formality rather than a gamble. This is the single biggest
  reliability difference between the two providers.
- **429 is an expected steady state, not an incident.** A free tier rate-limits by design,
  so the retry budget is longer here and honours `RetryInfo` when Google sends one.

Nothing in this file touches the network.
"""
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest
import requests
from django.test import override_settings

from llm.providers.gemini import API_ROOT, GeminiProvider, response_schema


@dataclass(frozen=True)
class Pick:
    index: int
    confidence: float
    reason: str


def response(status=200, *, text='{"index": 1, "confidence": 0.9, "reason": "ok"}',
             tokens=(120, 18), finish_reason="STOP", body=None):
    r = MagicMock(spec=requests.Response)
    r.status_code = status
    r.json.return_value = body if body is not None else {
        "candidates": [{
            "content": {"parts": [{"text": text}], "role": "model"},
            "finishReason": finish_reason,
        }],
        "usageMetadata": {
            "promptTokenCount": tokens[0],
            "candidatesTokenCount": tokens[1],
        },
        "modelVersion": "gemini-test",
    }
    r.text = text
    return r


@pytest.fixture()
def provider():
    with override_settings(LLM_API_KEY="", GEMINI_API_KEY="k-test",
                           LLM_MODEL="gemini-test"):
        yield GeminiProvider()


def run(provider, resp, schema=Pick, **over):
    kwargs = dict(prompt="pick", system="be terse", schema=schema,
                  max_output_tokens=256, temperature=0.0)
    kwargs.update(over)
    with patch("llm.providers.gemini.requests.post") as post, \
         patch("llm.providers.gemini.time.sleep"):
        post.side_effect = resp if isinstance(resp, list) else [resp]
        result = provider.complete(**kwargs)
    return result, post


# ---------------------------------------------------------------------------
# the request it builds
# ---------------------------------------------------------------------------

def test_posts_to_generate_content_for_the_configured_model(provider):
    _, post = run(provider, response())
    assert post.call_args.args[0] == f"{API_ROOT}/models/gemini-test:generateContent"


def test_sends_the_key_as_a_header_not_a_query_parameter(provider):
    """A key in the URL lands in every proxy log and every exception message."""
    _, post = run(provider, response())
    assert post.call_args.kwargs["headers"]["x-goog-api-key"] == "k-test"
    assert "key=" not in post.call_args.args[0]


def test_wraps_the_prompt_in_the_contents_structure(provider):
    _, post = run(provider, response())
    body = post.call_args.kwargs["json"]
    assert body["contents"] == [{"role": "user", "parts": [{"text": "pick"}]}]


def test_sends_the_system_prompt_as_system_instruction(provider):
    _, post = run(provider, response())
    assert post.call_args.kwargs["json"]["systemInstruction"] == {
        "parts": [{"text": "be terse"}]
    }


def test_omits_system_instruction_when_there_is_none(provider):
    _, post = run(provider, response(), system=None)
    assert "systemInstruction" not in post.call_args.kwargs["json"]


def test_sends_generation_config(provider):
    _, post = run(provider, response())
    config = post.call_args.kwargs["json"]["generationConfig"]
    assert config["maxOutputTokens"] == 256
    assert config["temperature"] == 0.0


def test_constrains_the_output_to_json(provider):
    _, post = run(provider, response())
    config = post.call_args.kwargs["json"]["generationConfig"]
    assert config["responseMimeType"] == "application/json"


def test_sends_the_dataclass_as_a_response_schema(provider):
    """Server-side constraint — the reason this provider declines far less often."""
    _, post = run(provider, response())
    schema = post.call_args.kwargs["json"]["generationConfig"]["responseSchema"]
    assert schema["type"] == "OBJECT"
    assert set(schema["properties"]) == {"index", "confidence", "reason"}


def test_asks_for_no_schema_on_a_prose_request(provider):
    _, post = run(provider, response(text="just words"), schema=None)
    config = post.call_args.kwargs["json"]["generationConfig"]
    assert "responseSchema" not in config
    assert "responseMimeType" not in config


def test_sends_a_timeout(provider):
    _, post = run(provider, response())
    assert post.call_args.kwargs["timeout"]


# ---------------------------------------------------------------------------
# response_schema — the dataclass translation
# ---------------------------------------------------------------------------

def test_schema_maps_python_types_to_gemini_types():
    schema = response_schema(Pick)
    assert schema["properties"]["index"]["type"] == "INTEGER"
    assert schema["properties"]["confidence"]["type"] == "NUMBER"
    assert schema["properties"]["reason"]["type"] == "STRING"


def test_schema_marks_fields_without_defaults_required():
    assert set(response_schema(Pick)["required"]) == {"index", "confidence", "reason"}


def test_schema_leaves_defaulted_fields_optional():
    @dataclass(frozen=True)
    class WithDefault:
        needed: str
        optional: int = 0

    schema = response_schema(WithDefault)
    assert schema["required"] == ["needed"]
    assert "optional" in schema["properties"]


def test_schema_preserves_field_order():
    """Gemini emits properties in schema order, and a stable order keeps the response
    cache key stable across runs."""
    assert list(response_schema(Pick)["properties"]) == ["index", "confidence", "reason"]


# ---------------------------------------------------------------------------
# the answer it returns
# ---------------------------------------------------------------------------

def test_parses_the_value(provider):
    result, _ = run(provider, response())
    assert result.value == Pick(1, 0.9, "ok")


def test_records_token_counts(provider):
    result, _ = run(provider, response(tokens=(310, 42)))
    assert (result.tokens_in, result.tokens_out) == (310, 42)


def test_the_free_tier_costs_nothing(provider):
    """An unpriced model records 0 rather than an invented number."""
    result, _ = run(provider, response(tokens=(1000, 100)))
    assert result.cost_usd == 0.0


def test_a_priced_model_is_costed(provider):
    from llm.providers.gemini import PRICING
    model = next(iter(PRICING))
    rates = PRICING[model]
    with override_settings(GEMINI_API_KEY="k", LLM_MODEL=model):
        priced = GeminiProvider()
    result, _ = run(priced, response(tokens=(1_000_000, 1_000_000)))
    assert result.cost_usd == pytest.approx(rates[0] + rates[1])


def test_it_joins_multiple_text_parts(provider):
    body = {
        "candidates": [{"content": {"parts": [{"text": '{"index": 1, "confi'},
                                              {"text": 'dence": 0.5, "reason": "x"}'}]},
                        "finishReason": "STOP"}],
        "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 1},
    }
    result, _ = run(provider, response(body=body))
    assert result.value == Pick(1, 0.5, "x")


def test_schema_none_returns_prose(provider):
    result, _ = run(provider, response(text="just words"), schema=None)
    assert result.value == "just words"


# ---------------------------------------------------------------------------
# the ways it declines
# ---------------------------------------------------------------------------

def test_a_truncated_answer_names_max_tokens(provider):
    result, _ = run(provider, response(text='{"index": 1, "confi',
                                       finish_reason="MAX_TOKENS"))
    assert result.declined is True
    assert "MAX_TOKENS" in result.declined_reason


def test_a_safety_block_declines_and_says_so(provider):
    result, _ = run(provider, response(text="", finish_reason="SAFETY"))
    assert result.declined is True
    assert "SAFETY" in result.declined_reason


def test_a_prompt_level_block_declines(provider):
    """No candidates at all — Gemini rejects the *prompt* rather than the completion."""
    body = {"promptFeedback": {"blockReason": "OTHER"}, "usageMetadata": {}}
    result, _ = run(provider, response(body=body))
    assert result.declined is True
    assert "OTHER" in result.declined_reason


def test_an_empty_candidate_list_declines(provider):
    result, _ = run(provider, response(body={"candidates": [], "usageMetadata": {}}))
    assert result.declined is True


def test_a_missing_api_key_declines_without_calling_out(provider):
    with override_settings(LLM_API_KEY="", GEMINI_API_KEY=""):
        keyless = GeminiProvider()
        with patch("llm.providers.gemini.requests.post") as post:
            result = keyless.complete(prompt="x", system=None, schema=Pick,
                                      max_output_tokens=64, temperature=0.0)
    assert result.declined is True
    assert post.call_count == 0


# ---------------------------------------------------------------------------
# quota — 429 is the free tier's normal weather
# ---------------------------------------------------------------------------

def test_retries_a_429_then_succeeds(provider):
    result, post = run(provider, [response(429), response()])
    assert post.call_count == 2
    assert result.value == Pick(1, 0.9, "ok")


def test_it_retries_a_429_more_than_once(provider):
    """A free tier rate-limits by design, so one retry is not a budget."""
    result, post = run(provider, [response(429), response(429), response()])
    assert post.call_count == 3
    assert result.declined is False


def test_it_gives_up_eventually_rather_than_hammering(provider):
    result, post = run(provider, [response(429)] * 20)
    assert post.call_count <= 6
    assert result.declined is True
    assert "429" in result.declined_reason


def test_it_honours_a_retry_delay_from_google(provider):
    """Google returns RetryInfo on quota errors; ignoring it just burns the budget."""
    quota = response(429, body={"error": {"code": 429, "status": "RESOURCE_EXHAUSTED",
                                          "details": [{
                                              "@type": "type.googleapis.com/google.rpc.RetryInfo",
                                              "retryDelay": "7s"}]}})
    with patch("llm.providers.gemini.requests.post") as post, \
         patch("llm.providers.gemini.time.sleep") as sleep:
        post.side_effect = [quota, response()]
        provider.complete(prompt="p", system=None, schema=Pick,
                          max_output_tokens=64, temperature=0.0)
    assert sleep.call_args.args[0] == pytest.approx(7.0)


def test_it_does_not_retry_a_400(provider):
    result, post = run(provider, [response(400), response()])
    assert post.call_count == 1
    assert result.declined is True


def test_it_does_not_retry_a_403(provider):
    """A bad or unauthorised key will be just as bad on the second attempt."""
    result, post = run(provider, [response(403), response()])
    assert post.call_count == 1
    assert result.declined is True


def test_a_transport_exception_declines_rather_than_raising(provider):
    result, _ = run(provider, [requests.ConnectionError("no route")] * 20)
    assert result.declined is True
    assert "no route" in result.declined_reason


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------

def test_it_satisfies_the_provider_protocol(provider):
    from llm.base import LLMProvider
    assert isinstance(provider, LLMProvider)


def test_it_is_registered_under_its_name():
    from llm.registry import PROVIDER_REGISTRY, LLMProviderName
    assert PROVIDER_REGISTRY[LLMProviderName.GEMINI] is GeminiProvider


def test_it_falls_back_to_the_generic_key():
    with override_settings(GEMINI_API_KEY="", LLM_API_KEY="generic"):
        assert GeminiProvider().api_key == "generic"


def test_a_provider_specific_key_wins():
    with override_settings(GEMINI_API_KEY="specific", LLM_API_KEY="generic"):
        assert GeminiProvider().api_key == "specific"
