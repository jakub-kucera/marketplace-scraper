"""A `FilterRule` that scores an ad against its reference price.

**Registered but not in `DEFAULT_RULE_NAMES`** — exactly how `price_model` ships, for
exactly the same reason: it is inverted relative to the other rules (it answers "is there
a reason to *send* this?"), so defaulting it on would mute every existing query. Enabling
it is a one-line `Query.filter_rule_names` edit on a single query.

**It never calls Zboží.** `run_filter` holds `select_for_update` locks while rules run,
and network I/O inside that window is forbidden — the same contract `PriceModel.predict`
carries. This rule reads only `RefProductLink` rows that an explicit rung-1/2 run already
persisted, and PASSes when there is none. That is what keeps the automatic path honest:
it can only act on matches a human or an earlier deliberate lookup produced.
"""
import logging

from bazos.filters import FilterResult
from bazos.models import AdDelivery

logger = logging.getLogger(__name__)

#: Only act on a link a person vouched for, or one the rules matched with high confidence.
#: Precision is not measurable yet (no outcome data — the same gap that keeps
#: PRICE_MODEL_SHADOW_MODE on), so the bar starts high rather than tuned.
MIN_CONFIDENCE = 0.8
#: An asking price at or below this fraction of the reference median is a deal.
DEAL_RATIO = 0.6


class ReferencePriceRule:
    """Rejects anything that is not cheap against its catalogue reference price.

    PASSes — deliberately, never rejects — when:
    - the ad has no reference link (nothing has looked it up yet),
    - the link has no product, or the product has fewer than two merchants,
    - the ad has no parsed price,
    - the match was low-confidence and unconfirmed.

    A lookup that never ran must not be able to silently drop every ad on a query that
    enabled this.
    """
    name = "reference_price"

    def apply(self, delivery: AdDelivery) -> tuple[FilterResult, str | None]:
        # Imported lazily: bazos.filters is imported at app-load time by callers that
        # must not pay for this package, and refprice.models imports bazos.models.
        from refprice.models import RefProductLink

        ad = delivery.ad
        if ad.price is None:
            return FilterResult.PASS, None

        link = (
            RefProductLink.objects.filter(ad=ad, product__isnull=False)
            .select_related("product").order_by("-confirmed_by_human", "-confidence")
            .first()
        )
        if link is None or link.product is None:
            return FilterResult.PASS, None
        if not link.confirmed_by_human and link.confidence < MIN_CONFIDENCE:
            return FilterResult.PASS, None

        product = link.product
        if not product.has_market or not product.median_czk:
            # One merchant is not a market; pricing against it would be worse than not
            # pricing at all.
            return FilterResult.PASS, None

        ratio = ad.price / product.median_czk
        if ratio <= DEAL_RATIO:
            return FilterResult.APPROVE, None
        return FilterResult.REJECT, (
            f"{ad.price} Kč is {ratio:.0%} of the {product.median_czk} Kč new price "
            f"({product.name})"
        )
