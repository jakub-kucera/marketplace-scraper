"""Read specs out of an ad's free text with an LLM, and store what came back.

`PRICE_MODEL_BENCHMARK.md` §3.1 is the reason this exists: **two extractor regexes were
worth more R² than the entire choice of estimator.** Extraction is the measured bottleneck,
and regexes over Czech prose are where the current extractor tops out — a listing that writes
"16/512" or "M1 Pro 14palcový" is legible to a reader and invisible to a pattern.

⚠️ **Nothing consumes this yet**, and that is deliberate: it ships inert the way the rest of
this app did. Feeding it to a `PriceModel` means deciding what happens when an extraction
disagrees with the regexes, and that is not a question to answer in passing.

**Why this lives in `llm/` and not in `bazos/`.** The dependency points inward: `bazos` must
stay deletable-independent of the apps built on it, which is why `refprice` registers its own
filter rule rather than being imported. The *table* is an `Ad` child, like `AdPriceScore`, and
so belongs to `bazos`; the code that fills it needs an LLM and so belongs here.

Two properties inherited rather than re-invented:

- **Declining is never an exception.** `llm.services.complete` returns a declined result for
  a refusal, unparseable output, a raising provider or an exhausted budget; all of them land
  here as a stored row with empty specs and a reason.
- **Inert by default.** `LLM_PROVIDER` is `NULL` out of the box, so this costs nothing and
  opens no socket until somebody configures a provider.
"""
import logging
from dataclasses import asdict, dataclass, fields

from django.conf import settings

from marketplace.models import Ad, AdSpecExtraction
from llm.prompts import load
from llm.services import complete

logger = logging.getLogger(__name__)

SPEC_PROMPT = "ad_specs"

#: Long enough for a dozen short values, short enough that a runaway answer is capped
#: before it costs anything worth noticing.
MAX_OUTPUT_TOKENS = 300


@dataclass(frozen=True)
class AdSpecs:
    """The extraction schema.

    Every field defaults to empty so the provider may omit any of them — which is the whole
    point of the prompt's "an absent key means the ad does not say". Plain types only:
    `parse_into` type-checks strictly, and a union would be waved through.
    """
    brand: str = ""
    model: str = ""
    model_code: str = ""
    year: int = 0
    cpu: str = ""
    ram_gb: int = 0
    storage_gb: int = 0
    storage_type: str = ""
    gpu: str = ""
    screen_inches: float = 0.0
    condition: str = ""


def _present(specs: AdSpecs) -> dict:
    """Drop the empty defaults, so a stored row says only what was actually read.

    Storing the zeroes would make "the ad does not say" indistinguishable from "the ad says
    zero", and something downstream would eventually average them.
    """
    return {
        field.name: value
        for field in fields(specs)
        if (value := getattr(specs, field.name)) not in ("", 0, 0.0)
    }


def extract_specs(ad: Ad) -> AdSpecExtraction:
    """Ask the configured provider for this ad's specs and persist the answer.

    Always writes a row, declined or not — `QueryRun`'s rule, and `AdPriceScore`'s. Keyed on
    `(ad, prompt_version)`, so re-running a prompt version updates its row while a new
    version starts a fresh one and leaves the old verdict readable.
    """
    prompt = load(SPEC_PROMPT)
    result = complete(
        prompt=prompt.render(
            title=ad.name,
            description=(ad.full_description or ad.short_description or "(none)"),
        ),
        system=prompt.system,
        schema=AdSpecs,
        prompt_name=prompt.name,
        prompt_version=prompt.version,
        max_output_tokens=MAX_OUTPUT_TOKENS,
    )

    specs = _present(result.value) if result.value is not None else {}
    row, _ = AdSpecExtraction.objects.update_or_create(
        ad=ad,
        prompt_version=prompt.version,
        defaults={
            "specs": specs,
            "provider": (settings.LLM_PROVIDER or "NULL").upper(),
            "model_name": result.model or "",
            "declined_reason": result.declined_reason,
        },
    )
    logger.info(
        "Spec extraction for ad %s: %s",
        ad.pk, result.declined_reason or f"{len(specs)} spec(s)",
    )
    return row


def as_dict(specs: AdSpecs) -> dict:
    """The full schema including empties — for a caller that wants every key present."""
    return asdict(specs)
