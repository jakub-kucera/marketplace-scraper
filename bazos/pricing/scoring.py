"""Compute and persist an `AdPriceScore`.

Sits between the registry (which produces a number) and the filter rule (which acts on it),
so the rule stays a predicate and the persistence lives in one place.
"""
import logging
from typing import Any

from bazos.models import Ad, AdPriceScore
from bazos.pricing.registry import get_price_model

logger = logging.getLogger(__name__)


def score_ad(ad: Ad, *, refresh: bool = False) -> AdPriceScore | None:
    """Score `ad` with whichever registered model claims it, and persist the result.

    Returns the stored row, or None when no model applies. A *declined* score is still
    stored -- with null numbers and a reason -- because "the model looked and had no opinion"
    is a different fact from "nothing ever looked", and only one of them is worth revisiting.

    Idempotent: the score is a pure function of the ad and the model version, so two
    deliveries of the same ad racing here converge on the same value. `update_or_create`
    on the `(ad, model_name)` unique constraint makes the write safe either way.
    """
    model = get_price_model(ad)
    if model is None:
        return None

    existing = None if refresh else AdPriceScore.objects.filter(ad=ad, model_name=model.name).first()
    if existing is not None and existing.model_version == model.version:
        return existing

    prediction = model.predict(ad)
    defaults: dict[str, Any] = {"model_version": model.version}
    if prediction is None:
        defaults.update(
            predicted=None, residual_log=None, discount_pct=None, z_score=None,
            seller_prior_ads=None, declined_reason="model declined (gates or missing artifact)",
        )
    else:
        defaults.update(
            predicted=prediction.predicted,
            residual_log=prediction.residual_log,
            discount_pct=prediction.discount_pct,
            z_score=prediction.z_score,
            seller_prior_ads=prediction.seller_prior_ads,
            declined_reason=None,
        )
    score, _ = AdPriceScore.objects.update_or_create(
        ad=ad, model_name=model.name, defaults=defaults
    )
    return score
