"""The PriceModel protocol and its result type.

A price model answers one question about one `Ad`: what should this listing cost, and how
unusual is the asking price? It says nothing about whether to notify anyone — that is a
per-`(ad, query)` decision and belongs to the filter layer (`PriceModelRule`).
"""
from dataclasses import dataclass
from typing import Protocol

from bazos.models import Ad


@dataclass(frozen=True)
class PricePrediction:
    """One model's verdict on one ad.

    `residual_log` is `ln(actual) - ln(predicted)`, so negative means cheaper than expected.
    `z_score` divides that by the seller's own residual spread, which is what makes the
    number comparable across seller types: a flat -25% is ~0.95 sigma for a first-time
    private seller but ~2.9 sigma for a high-volume dealer (docs/research/MACBOOK_PRICE_MODEL.md
    §5). `None` when there is no usable seller baseline.
    """
    predicted: int
    residual_log: float
    z_score: float | None
    seller_prior_ads: int
    #: The parsed inputs the prediction was computed from, JSON-serialisable, or None for
    #: a model that does not expose them. Persisted verbatim so a wrong-looking alert can
    #: be diagnosed: extraction is the measured weak point, not the model class -- two
    #: extractor regexes were worth more R2 than the entire choice of estimator
    #: (docs/research/PRICE_MODEL_BENCHMARK.md §3.1). Without this, "why did it think this
    #: was cheap" is unanswerable after the fact.
    features: dict | None = None

    @property
    def discount_pct(self) -> float:
        """Positive = below prediction (a discount). Negative = dearer than predicted."""
        import math
        return (1.0 - math.exp(self.residual_log)) * 100.0


class PriceModel(Protocol):
    """Structural protocol for price estimators. Implementations live in `estimators/`.

    Two contracts that are not expressible in the signature and matter:

    - **`predict` must not perform network I/O.** It is called from inside `run_filter`'s
      `select_for_update` transaction, and the JOB_QUEUE proposal rejects blocking network
      work in that window. CPU-only inference against a process-cached artifact is fine;
      an HTTP call is not.
    - **Returning `None` is the normal way to decline.** A model that cannot trust its own
      inputs (missing specs, no artifact, too few comparables) returns `None` rather than
      guessing, and the caller treats that as "no opinion".
    """
    name: str

    @property
    def version(self) -> str:
        """Artifact version, recorded on every score this model produces."""
        ...

    def applies_to(self, ad: Ad) -> bool:
        """Does this model claim this ad? Cheap, no DB, no network."""
        ...

    def predict(self, ad: Ad) -> PricePrediction | None:
        """Score the ad, or return None to decline. Must not perform network I/O."""
        ...
