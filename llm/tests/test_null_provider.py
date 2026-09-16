"""`NullProvider` — the default, and the reason the suite needs no key and no egress.

This is `DummyIPChanger`'s role: a real implementation of the protocol that honestly
reports it cannot do the thing, so every caller exercises its own decline path in dev
and in CI rather than only in production.
"""
from dataclasses import dataclass

from llm.providers.null import NullProvider


@dataclass(frozen=True)
class Pick:
    index: int


def complete(**over):
    kwargs = dict(prompt="anything", system=None, schema=Pick,
                  max_output_tokens=256, temperature=0.0)
    kwargs.update(over)
    return NullProvider().complete(**kwargs)


def test_it_declines():
    assert complete().declined is True


def test_it_says_why():
    assert "NULL" in complete().declined_reason


def test_it_costs_nothing():
    res = complete()
    assert (res.cost_usd, res.tokens_in, res.tokens_out) == (0.0, 0, 0)


def test_it_satisfies_the_protocol_structurally():
    from llm.base import LLMProvider
    assert isinstance(NullProvider(), LLMProvider)


def test_it_declines_prose_requests_too():
    """schema=None is the prose path; Null must decline there too, not return an empty string."""
    assert complete(schema=None).declined is True
