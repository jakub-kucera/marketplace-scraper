"""Rungs 3 and 4 — the only places this app asks an LLM anything.

**The model is never asked to invent an identity.** Rung 4 hands it a candidate list that
came out of the real catalogue and asks it to pick one or decline. That is the correction
to `HEUREKA_ZBOZI.md` §4d, which costed blind per-ad extraction and concluded — correctly,
on its evidence — that even a perfect extractor would not be sufficient. Closed-set
adjudication is a different and much smaller problem: ~340 tokens, auditable against the
list it was given, and it degrades to "no opinion" rather than to a wrong number.

Both rungs are inert under the shipped default (`LLM_PROVIDER=NULL`), and both decline
rather than raise, so nothing above them needs a fallback path of its own.
"""
import logging
from dataclasses import dataclass

from llm.prompts import load
from llm.services import complete
from refprice.providers.base import RefProductFacts

logger = logging.getLogger(__name__)

ADJUDICATE_PROMPT = "refprice_adjudicate"
PHRASE_PROMPT = "refprice_query_phrase"

#: -1 rather than a nullable index: `parse_into` type-checks plain types strictly, and a
#: sentinel keeps the schema a bare `int` instead of a union it would wave through.
NONE_OF_THEM = -1


@dataclass(frozen=True)
class Adjudication:
    index: int
    confidence: float
    reason: str


@dataclass(frozen=True)
class PhraseSuggestion:
    phrase: str
    brand: str
    model_code: str


@dataclass(frozen=True)
class Choice:
    facts: RefProductFacts | None
    confidence: float = 0.0
    reason: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    called: bool = False


def adjudicate(title: str, candidates: list[RefProductFacts]) -> Choice:
    """Rung 4: pick the candidate that is the same product, or decline."""
    if not candidates:
        # Nothing to choose between. Spending a call to be told so would be pure waste.
        return Choice(None, reason="no candidates to adjudicate")

    prompt = load(ADJUDICATE_PROMPT)
    listing = "\n".join(
        f"{i}) {c.name}"
        + (f" [{c.brand}]" if c.brand else "")
        + (f" — {c.shop_count} shops" if c.shop_count else "")
        for i, c in enumerate(candidates)
    )
    result = complete(
        prompt=prompt.render(title=title, candidates=listing),
        system=prompt.system,
        schema=Adjudication,
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        max_output_tokens=200,
    )

    def answered(facts: RefProductFacts | None, reason: str, confidence: float = 0.0) -> Choice:
        """Every return carries the meter — a decline costs tokens too, and losing that
        would understate the month."""
        return Choice(
            facts=facts, confidence=confidence, reason=reason,
            tokens_in=result.tokens_in, tokens_out=result.tokens_out,
            cost_usd=result.cost_usd, called=True,
        )

    if result.value is None:
        return answered(None, result.declined_reason or "declined")

    answer: Adjudication = result.value
    if answer.index == NONE_OF_THEM:
        return answered(None, answer.reason or "none of the candidates")
    if not 0 <= answer.index < len(candidates):
        # A hallucinated index must not become an IndexError three frames up.
        logger.warning("Adjudication returned out-of-range index %s of %s",
                       answer.index, len(candidates))
        return answered(None, f"out-of-range index {answer.index}")

    return answered(candidates[answer.index], answer.reason, answer.confidence)


def suggest_phrase(title: str, description: str = "") -> PhraseSuggestion:
    """Rung 3: when the rule normaliser left nothing searchable, ask for a phrase."""
    prompt = load(PHRASE_PROMPT)
    result = complete(
        prompt=prompt.render(title=title, description=description or "(none)"),
        system=prompt.system,
        schema=PhraseSuggestion,
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        max_output_tokens=150,
    )
    if result.value is None:
        return PhraseSuggestion(phrase="", brand="", model_code="")
    return result.value
