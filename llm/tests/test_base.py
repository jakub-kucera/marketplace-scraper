"""The result type and the shared JSON-into-dataclass parser.

`parse_into` lives in `base` rather than in each provider because every real provider
faces the identical problem — a model that was asked for JSON and answered with prose,
a fence, or a field short — and the repo's rule is that an uncertain path ends in a
decline, not an exception. Testing it here pins that for every provider at once.
"""
from dataclasses import dataclass

from llm.base import LLMResult, parse_into


@dataclass(frozen=True)
class Pick:
    index: int
    confidence: float
    reason: str


def result(**over):
    base = dict(
        value=None, raw="", provider="FAKE", model="fake-1",
        tokens_in=0, tokens_out=0, cost_usd=0.0, latency_ms=0,
        declined_reason=None, cached=False,
    )
    base.update(over)
    return LLMResult(**base)


# ---------------------------------------------------------------------------
# LLMResult
# ---------------------------------------------------------------------------

def test_declined_is_true_when_value_is_none():
    assert result(declined_reason="nope").declined is True


def test_declined_is_false_when_a_value_is_present():
    assert result(value=Pick(0, 1.0, "ok")).declined is False


def test_a_falsy_value_is_still_not_a_decline():
    """`0`/`""` are legitimate answers; only None means no opinion."""
    assert result(value=0).declined is False


# ---------------------------------------------------------------------------
# parse_into — the happy path
# ---------------------------------------------------------------------------

def test_parses_a_plain_json_object():
    value, reason = parse_into(Pick, '{"index": 2, "confidence": 0.9, "reason": "model code"}')
    assert value == Pick(2, 0.9, "model code")
    assert reason is None


def test_ignores_unknown_fields():
    """Models volunteer extra keys; that is not a reason to throw away a good answer."""
    value, _ = parse_into(Pick, '{"index": 1, "confidence": 0.5, "reason": "x", "notes": "chatty"}')
    assert value == Pick(1, 0.5, "x")


def test_unwraps_a_markdown_fenced_block():
    raw = 'Here you go:\n```json\n{"index": 0, "confidence": 0.8, "reason": "exact"}\n```\n'
    value, reason = parse_into(Pick, raw)
    assert value == Pick(0, 0.8, "exact")
    assert reason is None


def test_finds_a_bare_object_embedded_in_prose():
    value, _ = parse_into(Pick, 'I think {"index": 3, "confidence": 0.4, "reason": "weak"} fits.')
    assert value == Pick(3, 0.4, "weak")


def test_coerces_an_int_into_a_float_field():
    value, _ = parse_into(Pick, '{"index": 1, "confidence": 1, "reason": "ok"}')
    assert value == Pick(1, 1.0, "ok")
    assert isinstance(value.confidence, float)


# ---------------------------------------------------------------------------
# parse_into — every failure is a decline, never an exception
# ---------------------------------------------------------------------------

def test_missing_required_field_declines():
    value, reason = parse_into(Pick, '{"index": 1, "confidence": 0.5}')
    assert value is None
    assert reason is not None and "reason" in reason


def test_unparseable_text_declines():
    value, reason = parse_into(Pick, "I am afraid I cannot help with that.")
    assert value is None
    assert reason


def test_wrong_type_declines_rather_than_coercing_nonsense():
    value, reason = parse_into(Pick, '{"index": "two", "confidence": 0.5, "reason": "x"}')
    assert value is None
    assert reason


def test_empty_string_declines():
    value, reason = parse_into(Pick, "")
    assert value is None
    assert reason


def test_a_json_array_declines_because_an_object_was_asked_for():
    value, reason = parse_into(Pick, '[{"index": 1, "confidence": 0.5, "reason": "x"}]')
    assert value is None
    assert reason


def test_schema_none_returns_the_raw_text_unchanged():
    """A caller that wants prose passes schema=None and must not be JSON-parsed."""
    value, reason = parse_into(None, "  just words  ")
    assert value == "just words"
    assert reason is None


def test_schema_none_still_declines_on_empty_output():
    value, reason = parse_into(None, "   ")
    assert value is None
    assert reason
