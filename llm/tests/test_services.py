"""`complete()` — the audit-log and budget contracts.

Two rules carried over from elsewhere in this repo and pinned here:

- **Every call is persisted, success or failure.** `QueryRun`'s rule — a run row is written
  even when the run raises, because "it was tried and failed" is a different fact from
  "it was never tried".
- **Declining is never an exception.** `PriceModel.predict`'s rule. A provider that times
  out, refuses, or returns garbage must not be able to take its caller down.
"""
from dataclasses import dataclass
from datetime import timedelta

import pytest
from django.test import override_settings
from django.utils import timezone

from llm import services
from llm.base import LLMResult
from llm.models import LLMCall, LLMOutcome

pytestmark = pytest.mark.django_db


@dataclass(frozen=True)
class Pick:
    index: int


class FakeProvider:
    """Records what it was asked, and answers however the test wants."""

    name = "FAKE"

    def __init__(self, raw='{"index": 1}', tokens=(120, 8), cost=0.0004, exc=None):
        self.raw, self.tokens, self.cost, self.exc = raw, tokens, cost, exc
        self.calls = []

    def complete(self, *, prompt, system, schema, max_output_tokens, temperature):
        self.calls.append(prompt)
        if self.exc:
            raise self.exc
        from llm.base import parse_into
        value, reason = parse_into(schema, self.raw)
        return LLMResult(
            value=value, raw=self.raw, provider=self.name, model="fake-1",
            tokens_in=self.tokens[0], tokens_out=self.tokens[1], cost_usd=self.cost,
            latency_ms=12, declined_reason=reason, cached=False,
        )


def call(provider, **over):
    kwargs = dict(
        prompt="pick one", schema=Pick, prompt_name="refprice_adjudicate",
        prompt_version="v1", provider=provider,
    )
    kwargs.update(over)
    return services.complete(**kwargs)


# ---------------------------------------------------------------------------
# success
# ---------------------------------------------------------------------------

def test_success_returns_the_parsed_value():
    assert call(FakeProvider()).value == Pick(1)


def test_success_writes_one_llmcall_row():
    call(FakeProvider())
    assert LLMCall.objects.count() == 1


def test_the_row_records_the_prompt_identity_and_the_meter():
    call(FakeProvider(tokens=(300, 40), cost=0.0012))
    row = LLMCall.objects.get()
    assert row.outcome == LLMOutcome.OK
    assert (row.prompt_name, row.prompt_version) == ("refprice_adjudicate", "v1")
    assert (row.tokens_in, row.tokens_out) == (300, 40)
    assert float(row.cost_usd) == pytest.approx(0.0012)
    assert row.provider == "FAKE"
    assert row.model == "fake-1"


def test_the_provider_receives_the_prompt():
    p = FakeProvider()
    call(p, prompt="adjudicate these")
    assert p.calls == ["adjudicate these"]


# ---------------------------------------------------------------------------
# the provider declines — a normal outcome, still logged
# ---------------------------------------------------------------------------

def test_unparseable_output_declines_without_raising():
    res = call(FakeProvider(raw="sorry, no"))
    assert res.declined is True
    assert res.declined_reason


def test_a_decline_is_logged_as_declined_not_ok():
    call(FakeProvider(raw="sorry, no"))
    assert LLMCall.objects.get().outcome == LLMOutcome.DECLINED


def test_a_decline_still_bills_the_tokens_it_burned():
    """A refusal costs money; losing that would understate the monthly total."""
    call(FakeProvider(raw="no", cost=0.0009))
    assert float(LLMCall.objects.get().cost_usd) == pytest.approx(0.0009)


# ---------------------------------------------------------------------------
# the provider raises — never propagates
# ---------------------------------------------------------------------------

def test_a_raising_provider_returns_a_declined_result():
    res = call(FakeProvider(exc=RuntimeError("connection reset")))
    assert res.declined is True
    assert "connection reset" in res.declined_reason


def test_a_raising_provider_is_logged_as_error():
    call(FakeProvider(exc=RuntimeError("connection reset")))
    row = LLMCall.objects.get()
    assert row.outcome == LLMOutcome.ERROR
    assert "connection reset" in row.declined_reason


# ---------------------------------------------------------------------------
# budget ceiling — declines *before* spending
# ---------------------------------------------------------------------------

@override_settings(LLM_MONTHLY_BUDGET_USD=1.0)
def test_over_budget_declines():
    LLMCall.objects.create(
        prompt_name="x", prompt_version="v1", provider="FAKE", model="fake-1",
        tokens_in=0, tokens_out=0, cost_usd="1.500000", latency_ms=0,
        outcome=LLMOutcome.OK,
    )
    assert call(FakeProvider()).declined is True


@override_settings(LLM_MONTHLY_BUDGET_USD=1.0)
def test_over_budget_does_not_call_the_provider():
    """The whole point of a ceiling is that it stops spend, not that it reports it."""
    LLMCall.objects.create(
        prompt_name="x", prompt_version="v1", provider="FAKE", model="fake-1",
        tokens_in=0, tokens_out=0, cost_usd="1.500000", latency_ms=0,
        outcome=LLMOutcome.OK,
    )
    p = FakeProvider()
    call(p)
    assert p.calls == []


@override_settings(LLM_MONTHLY_BUDGET_USD=1.0)
def test_last_months_spend_does_not_count_against_this_month():
    old = LLMCall.objects.create(
        prompt_name="x", prompt_version="v1", provider="FAKE", model="fake-1",
        tokens_in=0, tokens_out=0, cost_usd="9.000000", latency_ms=0,
        outcome=LLMOutcome.OK,
    )
    LLMCall.objects.filter(pk=old.pk).update(created=timezone.now() - timedelta(days=45))
    assert call(FakeProvider()).declined is False


@override_settings(LLM_MONTHLY_BUDGET_USD=0)
def test_a_zero_budget_disables_calls_entirely():
    p = FakeProvider()
    assert call(p).declined is True
    assert p.calls == []


# ---------------------------------------------------------------------------
# the default provider
# ---------------------------------------------------------------------------

@override_settings(LLM_PROVIDER="NULL")
def test_the_default_provider_declines_and_touches_no_network():
    res = services.complete(prompt="anything", schema=Pick,
                            prompt_name="t", prompt_version="v1")
    assert res.declined is True
    assert res.cost_usd == 0.0


@override_settings(LLM_PROVIDER="NULL")
def test_the_null_provider_still_leaves_an_audit_row():
    services.complete(prompt="anything", schema=Pick, prompt_name="t", prompt_version="v1")
    assert LLMCall.objects.get().outcome == LLMOutcome.DECLINED


def test_month_to_date_cost_sums_only_this_month():
    # ages are 0 or >31 days on purpose: "1 day ago" crosses a month boundary on the 1st,
    # which would make this test fail once a month.
    for cost, age in ((0.25, 0), (0.50, 0), (7.00, 45)):
        row = LLMCall.objects.create(
            prompt_name="x", prompt_version="v1", provider="FAKE", model="fake-1",
            tokens_in=0, tokens_out=0, cost_usd=f"{cost:.6f}", latency_ms=0,
            outcome=LLMOutcome.OK,
        )
        if age:
            LLMCall.objects.filter(pk=row.pk).update(created=timezone.now() - timedelta(days=age))
    assert float(services.month_to_date_cost()) == pytest.approx(0.75)
