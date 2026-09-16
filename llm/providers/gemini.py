"""Google Gemini, over the Generative Language REST API.

Chosen alongside Anthropic for one measured reason: `docs/proposals/LLM_AD_REVIEW.md` §2f
found that **a free tier can carry this project's workload** — on the order of 1,500
requests/day, comfortably above a filtered candidate stream — and that under Google's
Gemini API terms the **paid-tier data terms apply to the free tier for EEA/UK/CH users**,
so free-tier prompts are not used to train models. That is what makes free viable here
rather than merely tempting. The same terms say not to submit personal information to the
unpaid services; public listing text is fine, and `refprice` sends nothing else.

Two things differ from `anthropic.py`, both deliberate:

- **`responseSchema` constrains the output server-side.** The dataclass is translated into
  the API's schema language, so the model is *structurally* prevented from answering with
  prose. `parse_into` becomes a formality rather than a gamble, and this is the single
  biggest reliability difference between the two providers.
- **429 is expected steady state, not an incident.** A free tier rate-limits by design, so
  the retry budget is longer and honours the `RetryInfo.retryDelay` Google returns.

Same call as `anthropic.py` on dependencies: `requests`, not the vendor SDK.
"""
import logging
import re
import time
from dataclasses import MISSING, fields, is_dataclass
from typing import Any, get_type_hints

import requests
from django.conf import settings

from llm.base import LLMResult, parse_into

logger = logging.getLogger(__name__)

API_ROOT = "https://generativelanguage.googleapis.com/v1beta"

#: USD per million tokens, (input, output), paid tier. **The free tier costs nothing**, so
#: an unlisted model records 0 — which is the honest answer for a free-tier key and a
#: visibly wrong one for a paid key on an unknown model, rather than an invented number.
PRICING: dict[str, tuple[float, float]] = {
    "gemini-2.5-flash": (0.30, 2.50),
    "gemini-2.5-pro": (1.25, 10.00),
}

#: Probed live 2026-09-16 and measured on this project's own adjudication prompt: correct
#: or defensibly correct on 7 of 7 archetypes, ~700 ms, ~450 in / 65 out tokens. Chosen as
#: the default because it was both the fastest and the cheapest tier that got them right.
#: A pinned name, not `gemini-flash-lite-latest`: a model that changes underneath makes a
#: stored result unattributable, which is the same reason prompts are versioned files.
DEFAULT_MODEL = "gemini-3.5-flash-lite"

#: Models whose price we have already complained about, so a free-tier key does not emit
#: the same warning on every call.
_UNPRICED_WARNED: set[str] = set()

#: Longer than Anthropic's: on a free tier a 429 is the normal weather, not a failure.
MAX_ATTEMPTS = 6
RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})
BACKOFF_SECONDS = 2.0
#: Never sleep longer than this on a server-supplied RetryInfo — a quota that resets
#: tomorrow would otherwise block the caller for hours.
MAX_RETRY_DELAY = 30.0

_TYPES: dict[Any, str] = {
    int: "INTEGER",
    float: "NUMBER",
    str: "STRING",
    bool: "BOOLEAN",
}

_DELAY = re.compile(r"([\d.]+)s")


def response_schema(schema: type) -> dict:
    """Translate a dataclass into the API's schema language.

    Field order is preserved because Gemini emits properties in schema order, and a stable
    output order keeps `llm.services`' response-cache key stable across runs.
    """
    hints = get_type_hints(schema)
    properties: dict[str, dict] = {}
    required: list[str] = []
    for field in fields(schema):
        annotation = hints.get(field.name, str)
        properties[field.name] = {"type": _TYPES.get(annotation, "STRING")}
        if field.default is MISSING and field.default_factory is MISSING:
            required.append(field.name)
    return {"type": "OBJECT", "properties": properties, "required": required}


def _retry_delay(payload: object) -> float | None:
    """Pull `RetryInfo.retryDelay` out of a quota error, if Google sent one."""
    if not isinstance(payload, dict):
        return None
    for detail in (payload.get("error") or {}).get("details") or []:
        if not isinstance(detail, dict):
            continue
        match = _DELAY.search(str(detail.get("retryDelay", "")))
        if match:
            return min(float(match.group(1)), MAX_RETRY_DELAY)
    return None


class GeminiProvider:
    name = "GEMINI"

    def __init__(self) -> None:
        # A provider-specific key wins, so both backends can be configured at once and
        # switching is a one-line LLM_PROVIDER change.
        self.api_key = getattr(settings, "GEMINI_API_KEY", "") or settings.LLM_API_KEY
        self.model = settings.LLM_MODEL or DEFAULT_MODEL

    def list_models(self) -> list[str]:
        """Which models this key can actually reach.

        Optional — not a `LLMProvider` protocol member, read with `getattr` by
        `manage.py llm_check --models`. Being able to complete does not imply being able
        to enumerate, and the free tier's model list changes often enough that guessing a
        name from documentation is worse than asking.
        """
        if not self.api_key:
            return []
        try:
            response = requests.get(
                f"{API_ROOT}/models",
                headers={"x-goog-api-key": self.api_key},
                timeout=settings.LLM_TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            logger.warning("Could not list Gemini models: %s", exc)
            return []
        return sorted(
            model.get("name", "").removeprefix("models/")
            for model in payload.get("models") or []
            if "generateContent" in (model.get("supportedGenerationMethods") or [])
        )

    def _cost(self, tokens_in: int, tokens_out: int) -> float:
        rates = PRICING.get(self.model)
        if rates is None:
            # Correct for a free-tier key and *wrong* for a paid one, so say so once:
            # LLM_MONTHLY_BUDGET_USD cannot protect spend it is never told about.
            if self.model not in _UNPRICED_WARNED:
                _UNPRICED_WARNED.add(self.model)
                logger.warning(
                    "No price listed for Gemini model %r — recording cost 0. Correct on "
                    "the free tier; on a paid key the monthly budget will not see this "
                    "spend until the model is added to gemini.PRICING.", self.model,
                )
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
            return self._declined("no API key (set GEMINI_API_KEY or LLM_API_KEY)")

        generation_config: dict[str, Any] = {
            "maxOutputTokens": max_output_tokens,
            "temperature": temperature,
        }
        if schema is not None and is_dataclass(schema):
            generation_config["responseMimeType"] = "application/json"
            generation_config["responseSchema"] = response_schema(schema)

        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": generation_config,
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}

        # Header, not `?key=` — a key in the URL lands in every proxy log and in the text
        # of every exception that quotes the request.
        headers = {"x-goog-api-key": self.api_key, "content-type": "application/json"}
        url = f"{API_ROOT}/models/{self.model}:generateContent"

        started = time.monotonic()
        last_problem = "no attempt made"

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                response = requests.post(url, headers=headers, json=body,
                                         timeout=settings.LLM_TIMEOUT)
            except requests.RequestException as exc:
                last_problem = f"{type(exc).__name__}: {exc}"
                if attempt == MAX_ATTEMPTS:
                    break
                time.sleep(BACKOFF_SECONDS * attempt)
                continue

            if response.status_code in RETRY_STATUSES:
                last_problem = f"HTTP {response.status_code} from generateContent"
                if attempt == MAX_ATTEMPTS:
                    break
                try:
                    payload = response.json()
                except ValueError:
                    payload = None
                time.sleep(_retry_delay(payload) or BACKOFF_SECONDS * attempt)
                continue

            if response.status_code != 200:
                # 400 (bad request), 403 (key/permission): not retryable.
                return self._declined(
                    f"HTTP {response.status_code} from generateContent",
                    latency_ms=int((time.monotonic() - started) * 1000),
                )

            return self._interpret(response, schema, started)

        return self._declined(last_problem,
                              latency_ms=int((time.monotonic() - started) * 1000))

    def _interpret(self, response: requests.Response, schema: type | None,
                   started: float) -> LLMResult:
        latency_ms = int((time.monotonic() - started) * 1000)
        try:
            payload = response.json()
        except ValueError:
            return self._declined("response body was not JSON", raw=response.text[:2000],
                                  latency_ms=latency_ms)

        usage = payload.get("usageMetadata") or {}
        tokens = (int(usage.get("promptTokenCount", 0) or 0),
                  int(usage.get("candidatesTokenCount", 0) or 0))
        cost = self._cost(*tokens)

        candidates = payload.get("candidates") or []
        if not candidates:
            # The *prompt* was rejected, not the completion — a different fact, and one
            # that a retry will never fix.
            block = (payload.get("promptFeedback") or {}).get("blockReason")
            return self._declined(
                f"no candidates returned (promptFeedback: {block or 'none'})",
                latency_ms=latency_ms, tokens=tokens, cost=cost,
            )

        candidate = candidates[0]
        text = "".join(
            part.get("text", "")
            for part in (candidate.get("content") or {}).get("parts") or []
        )

        finish = candidate.get("finishReason")
        if finish and finish not in {"STOP", "MAX_TOKENS"}:
            # SAFETY, RECITATION, PROHIBITED_CONTENT… — naming it is the difference
            # between "the model is bad" and "this prompt trips a filter".
            return self._declined(f"finishReason {finish}", raw=text,
                                  latency_ms=latency_ms, tokens=tokens, cost=cost)
        if finish == "MAX_TOKENS":
            return self._declined("finishReason MAX_TOKENS — output truncated", raw=text,
                                  latency_ms=latency_ms, tokens=tokens, cost=cost)

        value, reason = parse_into(schema, text)
        return LLMResult(
            value=value, raw=text, provider=self.name, model=self.model,
            tokens_in=tokens[0], tokens_out=tokens[1], cost_usd=cost,
            latency_ms=latency_ms, declined_reason=reason,
        )
