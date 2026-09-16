"""Anthropic Messages API, over `requests`.

No vendor SDK on purpose. It is the same call `bazos/pricing` makes when it evaluates a
linear model with a dot product rather than adding numpy to an ARM64 Pi image: one
endpoint does not justify a dependency, and `requests` is already a dependency here.

The retry budget is deliberately narrow — 429 and 5xx only. A 400 or a 401 will be exactly
as wrong on the second attempt, and retrying a refusal spends money to be refused again.
"""
import json
import logging
import time

import requests
from django.conf import settings

from llm.base import LLMResult, parse_into

logger = logging.getLogger(__name__)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"

#: USD per million tokens, (input, output). An unlisted model prices at zero and says so
#: in the log — a visible zero beats an invented number in a table nobody will revisit.
PRICING: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-opus-5": (5.0, 25.0),
}

MAX_ATTEMPTS = 4
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
BACKOFF_SECONDS = 2.0


class AnthropicProvider:
    name = "ANTHROPIC"

    def __init__(self) -> None:
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL

    def _cost(self, tokens_in: int, tokens_out: int) -> float:
        rates = PRICING.get(self.model)
        if rates is None:
            logger.warning("No price for model %r — recording cost 0", self.model)
            return 0.0
        return (tokens_in * rates[0] + tokens_out * rates[1]) / 1_000_000

    def _declined(self, reason: str, *, raw: str = "", latency_ms: int = 0,
                  tokens: tuple[int, int] = (0, 0), cost: float = 0.0) -> LLMResult:
        return LLMResult(
            value=None, raw=raw, provider=self.name, model=self.model,
            tokens_in=tokens[0], tokens_out=tokens[1], cost_usd=cost,
            latency_ms=latency_ms, declined_reason=reason,
        )

    def complete(
        self,
        *,
        prompt: str,
        system: str | None,
        schema: type | None,
        max_output_tokens: int,
        temperature: float,
    ) -> LLMResult:
        if not self.api_key:
            return self._declined("LLM_API_KEY is not set")

        body: dict = {
            "model": self.model,
            "max_tokens": max_output_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            body["system"] = system

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": API_VERSION,
            "content-type": "application/json",
        }

        started = time.monotonic()
        last_problem = "no attempt made"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = requests.post(
                    API_URL, headers=headers, json=body, timeout=settings.LLM_TIMEOUT
                )
            except requests.RequestException as exc:
                last_problem = f"{type(exc).__name__}: {exc}"
                if attempt == MAX_ATTEMPTS:
                    break
                time.sleep(BACKOFF_SECONDS * attempt)
                continue

            if response.status_code in RETRY_STATUSES:
                last_problem = f"HTTP {response.status_code} from the Messages API"
                if attempt == MAX_ATTEMPTS:
                    break
                time.sleep(BACKOFF_SECONDS * attempt)
                continue

            if response.status_code != 200:
                # 4xx other than 429: not retryable, and the body usually says why.
                return self._declined(
                    f"HTTP {response.status_code} from the Messages API",
                    latency_ms=int((time.monotonic() - started) * 1000),
                )

            return self._interpret(response, schema, started)

        return self._declined(
            last_problem, latency_ms=int((time.monotonic() - started) * 1000)
        )

    def _interpret(self, response: requests.Response, schema: type | None,
                   started: float) -> LLMResult:
        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return self._declined("response body was not JSON", raw=response.text[:2000],
                                  latency_ms=latency_ms)

        usage = payload.get("usage") or {}
        tokens = (int(usage.get("input_tokens", 0)), int(usage.get("output_tokens", 0)))
        cost = self._cost(*tokens)

        text = "".join(
            block.get("text", "")
            for block in payload.get("content") or []
            if block.get("type") == "text"
        )

        stop_reason = payload.get("stop_reason")
        if stop_reason == "max_tokens":
            # Almost always mid-JSON, so parse_into would decline anyway — but naming the
            # cause is the difference between "the model is bad" and "raise max_tokens".
            return self._declined(
                "stopped on max_tokens — output truncated",
                raw=text, latency_ms=latency_ms, tokens=tokens, cost=cost,
            )

        value, reason = parse_into(schema, text)
        return LLMResult(
            value=value, raw=text, provider=self.name, model=self.model,
            tokens_in=tokens[0], tokens_out=tokens[1], cost_usd=cost,
            latency_ms=latency_ms, declined_reason=reason,
        )
