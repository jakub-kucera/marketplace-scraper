"""Name-keyed registry of price models.

The third instance of a pattern this codebase already uses twice -- `MarketplaceScraper` /
`_build_scrapers` and `RULE_REGISTRY` / `build_rule_engine`. Adding a model for another
category or marketplace is a new entry here plus a module in `estimators/`; nothing in the
filter or the scoring service needs to change.
"""
import logging

from marketplace.models import Ad
from marketplace.pricing.base import PriceModel
from marketplace.pricing.estimators.iphone import IPhonePriceModel
from marketplace.pricing.estimators.macbook import MacbookPriceModel

logger = logging.getLogger(__name__)

#: Insertion order does **not** decide which model claims an ad -- `get_price_model` declines
#: when two of them do, so reordering this literal cannot silently re-label anything. Order
#: still matters in one place: `AdAdmin.get_queryset` ranks by it, because SQL cannot run
#: `applies_to` (docs/backlog/PRICE_MODEL_DEFECTS.md §8, §8.1, §9).
MODEL_REGISTRY: dict[str, PriceModel] = {
    "macbook": MacbookPriceModel(),
    "iphone": IPhonePriceModel(),
}


def get_price_model(ad: Ad) -> PriceModel | None:
    """The model that claims this ad, or None. No DB, no network.

    `marketplaces` is checked before `applies_to` so a model never has to defend itself
    against another site's text, and so adding a marketplace is a registry-visible decision
    rather than a line buried in each estimator.

    **An ad claimed by more than one model is claimed by none.** Returning the first match
    made registry order decide silently, and order cannot express the answer an ambiguous ad
    actually has: a title reading `iPhone 13, k nemu pridam i MacBook Air obal` names two
    product families and neither model is fitted on it. Declining is the safe direction — it
    costs one unscored listing, where guessing costs a confident number from the wrong
    model's coefficients. Measured overlap was 7 ads corpus-wide, and the zero that looks
    reassuring on an iPhone query is an artifact of the 254-character preview: in full text
    the cross-family token appears 20x more often, so this must hold before
    `load_full_description` is turned on anywhere (docs/backlog/PRICE_MODEL_DEFECTS.md §8.1).
    """
    claimants = [
        model for model in MODEL_REGISTRY.values()
        if ad.marketplace in model.marketplaces and model.applies_to(ad)
    ]
    if len(claimants) == 1:
        return claimants[0]
    if claimants:
        logger.warning(
            "Ad %s is claimed by %s; declining rather than letting registry order decide",
            ad.pk, [m.name for m in claimants],
        )
    return None
