"""Name-keyed registry of price models.

The third instance of a pattern this codebase already uses twice -- `MarketplaceScraper` /
`_build_scrapers` and `RULE_REGISTRY` / `build_rule_engine`. Adding a model for another
category or marketplace is a new entry here plus a module in `estimators/`; nothing in the
filter or the scoring service needs to change.
"""
from bazos.models import Ad
from bazos.pricing.base import PriceModel
from bazos.pricing.estimators.macbook import MacbookPriceModel

#: Insertion order is selection order -- `get_price_model` returns the first model that
#: claims an ad, so a narrower model must be registered before a broader one.
MODEL_REGISTRY: dict[str, PriceModel] = {
    "macbook": MacbookPriceModel(),
}


def get_price_model(ad: Ad) -> PriceModel | None:
    for model in MODEL_REGISTRY.values():
        if model.applies_to(ad):
            return model
    return None
