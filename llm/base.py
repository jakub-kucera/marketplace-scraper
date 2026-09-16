"""The `LLMProvider` protocol, its result type, and the shared output parser.

Design notes in `docs/proposals/PRICE_REFERENCE_SERVICE.md` §2. Two contracts here are not
expressible in the signature and are the reason this module exists at all:

- **Declining is normal and is never an exception.** A refusal, a truncated answer or
  unparseable JSON all end in `value=None` plus a `declined_reason`. This is the rule
  `PriceModel.predict` already follows ("returning `None` is the normal way to decline")
  and the same one `bazos/pricing` states as "every uncertain path is neutral, never
  rejecting". A component that cannot answer must not be able to take its caller down.
- **No network I/O inside a `select_for_update` transaction.** `run_filter` holds row locks
  while it runs rules, so nothing here may be called from a filter rule. It is why the
  reference-price feature is explicit-only.
"""
import json
import re
from dataclasses import MISSING, dataclass, fields, is_dataclass
from typing import Any, Generic, Protocol, TypeVar, get_type_hints, runtime_checkable

T = TypeVar("T")

#: ```json … ``` or a bare ``` … ``` block — models wrap JSON in one unprompted.
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    """One provider's answer, whether or not it managed to answer.

    `raw` is kept even on a decline: when a prompt starts failing, the model's actual words
    are the only thing that explains why, and they are gone by the time anyone looks.
    """
    value: T | None
    raw: str
    provider: str
    model: str
    tokens_in: int
    tokens_out: int
    cost_usd: float
    latency_ms: int
    declined_reason: str | None = None
    cached: bool = False

    @property
    def declined(self) -> bool:
        """True when there is no answer. Note a falsy `value` (0, "") is still an answer."""
        return self.value is None


@runtime_checkable
class LLMProvider(Protocol):
    """Structural protocol for completion backends. Implementations live in `providers/`.

    `complete` must not raise for a model-side failure — that is what `declined_reason` is
    for. Raising is reserved for a genuinely broken transport, and `services.complete`
    catches even that so the caller never sees it.
    """
    name: str

    def complete(
        self,
        *,
        prompt: str,
        system: str | None,
        schema: type | None,
        max_output_tokens: int,
        temperature: float,
    ) -> LLMResult:
        ...


def _extract_json(raw: str) -> str | None:
    """Recover a JSON object from prose, a fenced block, or a clean response."""
    candidates = [raw]
    fenced = _FENCE.search(raw)
    if fenced:
        candidates.insert(0, fenced.group(1))
    # last resort: the span between the first { and the last }
    start, end = raw.find("{"), raw.rfind("}")
    if start != -1 and end > start:
        candidates.append(raw[start:end + 1])
    for candidate in candidates:
        candidate = candidate.strip()
        if not candidate:
            continue
        try:
            json.loads(candidate)
        except ValueError:
            continue
        return candidate
    return None


def _coerce(value: Any, annotation: Any) -> tuple[bool, Any]:
    """Accept a value for a field, widening int→float but never guessing across types."""
    if annotation is float and type(value) is int:
        return True, float(value)
    if annotation in (int, float) and isinstance(value, bool):
        # bool is a subclass of int; `true` is not a number anyone meant to send.
        return False, None
    if isinstance(annotation, type) and isinstance(value, annotation):
        return True, value
    if not isinstance(annotation, type):
        # Optionals, unions, containers — not type-checked here on purpose.
        return True, value
    return False, None


def parse_into(schema: type | None, raw: str) -> tuple[Any, str | None]:
    """Turn a model's raw output into `schema`, or explain why it could not be done.

    Returns `(value, None)` on success and `(None, reason)` on any failure — including an
    empty response, which is the commonest one and the easiest to mistake for a valid
    empty answer.
    """
    if not raw or not raw.strip():
        return None, "empty response"

    if schema is None:
        return raw.strip(), None

    if not is_dataclass(schema):
        return None, f"schema {schema!r} is not a dataclass"

    payload = _extract_json(raw)
    if payload is None:
        return None, f"no JSON object found in {raw[:120]!r}"

    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        return None, f"expected a JSON object, got {type(parsed).__name__}"

    hints = get_type_hints(schema)
    kwargs: dict[str, Any] = {}
    for field in fields(schema):
        if field.name not in parsed:
            if field.default is MISSING and field.default_factory is MISSING:
                return None, f"missing required field {field.name!r}"
            continue
        ok, coerced = _coerce(parsed[field.name], hints.get(field.name, Any))
        if not ok:
            return None, (
                f"field {field.name!r} expected {hints[field.name]!r}, "
                f"got {type(parsed[field.name]).__name__}"
            )
        kwargs[field.name] = coerced

    return schema(**kwargs), None
