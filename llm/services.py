"""The one entry point callers use, and the two guards that wrap every provider call.

`complete()` is deliberately the only public function: the budget ceiling and the audit
row are not optional decorations a caller can forget, so they live on the inside of the
boundary rather than being every caller's responsibility.
"""
import dataclasses
import hashlib
import logging
import time
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.db.models import Sum
from django.utils import timezone

from llm.base import LLMResult
from llm.models import LLMCall, LLMOutcome
from llm.registry import get_provider

logger = logging.getLogger(__name__)

DEFAULT_MAX_OUTPUT_TOKENS = 512
CACHE_PREFIX = "llm:v1:"


def cache_key(*, provider: str, model: str, prompt_name: str, prompt_version: str,
              prompt: str, system: str | None, schema: type | None) -> str:
    """Identical input under the same prompt *version* must not be billed twice.

    The version is part of the key because that is the whole point of versioning a
    prompt — v2 is allowed to answer differently, and must not read v1's answer. The
    schema is part of it because the cached object is an *instance* of that schema:
    without it, the same prompt asked for a different dataclass hands back the wrong type.
    """
    schema_id = f"{schema.__module__}.{schema.__qualname__}" if schema else "-"
    digest = hashlib.sha256(
        "\x1f".join(
            (provider, model, prompt_name, prompt_version, prompt, system or "", schema_id)
        ).encode("utf-8")
    ).hexdigest()
    return f"{CACHE_PREFIX}{digest}"


def month_to_date_cost() -> Decimal:
    """Spend since the 1st of the current month, in USD."""
    start = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = LLMCall.objects.filter(created__gte=start).aggregate(t=Sum("cost_usd"))["t"]
    return total or Decimal("0")


def _record(result: LLMResult, *, prompt_name: str, prompt_version: str, outcome: str) -> None:
    LLMCall.objects.create(
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        provider=result.provider,
        model=result.model,
        tokens_in=result.tokens_in,
        tokens_out=result.tokens_out,
        cost_usd=Decimal(str(result.cost_usd)),
        latency_ms=result.latency_ms,
        cached=result.cached,
        outcome=outcome,
        declined_reason=result.declined_reason or "",
    )


def complete(
    *,
    prompt: str,
    system: str | None = None,
    schema: type | None = None,
    prompt_name: str = "adhoc",
    prompt_version: str = "-",
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    temperature: float = 0.0,
    provider: Any = None,
) -> LLMResult:
    """Run one completion. Never raises; a failure comes back as a declined `LLMResult`.

    `provider` accepts an instance for tests and for a caller that has already resolved
    one; otherwise `settings.LLM_PROVIDER` decides.
    """
    impl = provider if provider is not None else get_provider()
    result: LLMResult

    budget = Decimal(str(settings.LLM_MONTHLY_BUDGET_USD))
    spent = month_to_date_cost()
    if spent >= budget:
        # Decline *before* calling out. A ceiling that reports overspend after the fact
        # is not a ceiling — this is the one failure mode here that costs real money.
        reason = f"monthly budget exhausted: ${spent} of ${budget}"
        logger.warning("LLM call declined — %s", reason)
        result = LLMResult(
            value=None, raw="", provider=getattr(impl, "name", "?"),
            model=settings.LLM_MODEL, tokens_in=0, tokens_out=0,
            cost_usd=0.0, latency_ms=0, declined_reason=reason,
        )
        _record(result, prompt_name=prompt_name, prompt_version=prompt_version,
                outcome=LLMOutcome.DECLINED)
        return result

    ttl = int(getattr(settings, "LLM_CACHE_SECONDS", 0) or 0)
    key = cache_key(
        provider=getattr(impl, "name", "?"), model=settings.LLM_MODEL,
        prompt_name=prompt_name, prompt_version=prompt_version,
        prompt=prompt, system=system, schema=schema,
    )
    if ttl:
        hit = cache.get(key)
        if hit is not None:
            # Billed zero: the money was spent on the first call, and counting it again
            # would close the monthly budget early. Still logged, so "how often was this
            # asked" stays answerable.
            result = dataclasses.replace(hit, cached=True, cost_usd=0.0, latency_ms=0)
            _record(result, prompt_name=prompt_name, prompt_version=prompt_version,
                    outcome=LLMOutcome.OK)
            return result

    started = time.monotonic()
    try:
        result = impl.complete(
            prompt=prompt,
            system=system,
            schema=schema,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )
    except Exception as exc:  # noqa: BLE001 — a broken transport must not reach the caller
        elapsed = int((time.monotonic() - started) * 1000)
        reason = f"{type(exc).__name__}: {exc}"
        logger.exception("LLM provider raised — %s", reason)
        result = LLMResult(
            value=None, raw="", provider=getattr(impl, "name", "?"),
            model=settings.LLM_MODEL, tokens_in=0, tokens_out=0,
            cost_usd=0.0, latency_ms=elapsed, declined_reason=reason,
        )
        _record(result, prompt_name=prompt_name, prompt_version=prompt_version,
                outcome=LLMOutcome.ERROR)
        return result

    outcome = LLMOutcome.DECLINED if result.declined else LLMOutcome.OK
    _record(result, prompt_name=prompt_name, prompt_version=prompt_version, outcome=outcome)
    if ttl and not result.declined:
        # Declines are deliberately not cached: a refusal or a timeout is usually
        # transient, and caching one would freeze a bad answer in place for its TTL.
        cache.set(key, result, ttl)
    return result
