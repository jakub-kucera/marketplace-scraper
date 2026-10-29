"""Compute and persist an `AdPriceScore`.

Sits between the registry (which produces a number) and the filter rule (which acts on it),
so the rule stays a predicate and the persistence lives in one place.
"""
import logging
from typing import Any

from marketplace.models import Ad, AdPriceScore
from marketplace.pricing.registry import get_price_model

logger = logging.getLogger(__name__)


#: `AdPriceScore.declined_reason` is varchar(255).
MAX_DECLINE_REASON = 255


def _decline_reason(model, ad: Ad) -> str:
    """Why this model had no opinion, as specifically as the model will say.

    `explain_decline` is optional on a model, and is allowed to fail: a score that records
    *nothing* is worse than one that records a vague reason, so an explanation that raises
    must not take the row down with it. Same principle as the rest of this package — every
    uncertain path stays neutral.
    """
    explain = getattr(model, "explain_decline", None)
    if explain is None:
        return "model declined (no reason given)"
    try:
        return (explain(ad) or "")[:MAX_DECLINE_REASON] or "model declined (empty reason)"
    except Exception:  # pragma: no cover - defensive; a reason must never lose the row
        logger.exception("explain_decline failed for model %r on ad %s", model.name, ad.pk)
        return "model declined (explanation failed)"


def score_ad(ad: Ad, *, refresh: bool = False) -> AdPriceScore | None:
    """Score `ad` with whichever registered model claims it, and persist the result.

    Returns the stored row, or None when no model applies. A *declined* score is still
    stored -- with null numbers and a reason -- because "the model looked and had no opinion"
    is a different fact from "nothing ever looked", and only one of them is worth revisiting.

    Idempotent: the score is a pure function of the ad and the model version, so two
    deliveries of the same ad racing here converge on the same value. `update_or_create`
    on the `(ad, model_name)` unique constraint makes the write safe either way.

    ⚠️ **The freshness check below keys on the artifact version alone, which is the wrong
    key for anything the *code* persists.** `features` is the first such field: a row
    written before that code shipped matches on `model_version`, short-circuits here, and
    keeps its null `features` forever — re-running the pipeline over the same ad will
    never fix it, because the row is considered fresh. So when you add a persisted field
    to `AdPriceScore`, follow it with `manage.py rescore_ads --missing-<field>`.

    Do not "fix" this by bumping the artifact version. `model_version` records which
    artifact produced a row and is what makes a bad model's output findable; falsifying it
    to force recomputation destroys that, and needs repeating on every code change.
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
            seller_prior_ads=None, features=None,
            declined_reason=_decline_reason(model, ad),
        )
    else:
        defaults.update(
            predicted=prediction.predicted,
            residual_log=prediction.residual_log,
            discount_pct=prediction.discount_pct,
            z_score=prediction.z_score,
            seller_prior_ads=prediction.seller_prior_ads,
            features=prediction.features,
            declined_reason=None,
        )
    score, _ = AdPriceScore.objects.update_or_create(
        ad=ad, model_name=model.name, defaults=defaults
    )
    return score
