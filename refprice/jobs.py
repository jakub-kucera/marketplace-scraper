"""Reference-price lookups as queued tasks.

These live here rather than in `bazos/jobs.py` for the reason the app is built around: the
dependency points inward, and `bazos` imports nothing from `refprice`. The schedule is
contributed through `bazos.jobs.register_schedule` at `AppConfig.ready()`, the same seam the
filter rule already uses.

⚠️ **Zboží, not Bazos.** Nothing here touches the Tor session, so these are among the few
jobs that cannot be stuck behind a delisting sweep — which is exactly why the admin action
that used to do this work *inside the request* is the cheapest thing to port.
"""
import logging
from io import StringIO

from django.core.management import call_command

logger = logging.getLogger(__name__)

#: Dotted paths, because that is what django-q2 persists in a `Schedule` row.
LOOKUP_REFERENCE_PRICE = "refprice.jobs.lookup_reference_price"
REFRESH_STALE_REFERENCE_PRICES = "refprice.jobs.refresh_stale_reference_prices"


def lookup_reference_price(ad_pk: int) -> str:
    """Resolve one ad against Zboží and persist the link. One ad, one task.

    Not a batch: a selection of fifty ads enqueues fifty of these, so one failure loses one
    lookup rather than forty-nine and each gets its own row in the run log.

    Takes a pk rather than an `Ad` — django-q2 pickles task arguments, so a model instance
    would be a *snapshot* taken when the task was queued and written back over whatever
    changed in between.
    """
    from bazos.models import Ad
    from refprice.results import ReferenceRequest
    from refprice.services import lookup_reference_price as resolve

    ad = Ad.objects.get(pk=ad_pk)
    result = resolve(
        ReferenceRequest(title=ad.name, description=ad.short_description or ""),
        ad=ad,
    )
    logger.info("Reference lookup for ad %s: %s", ad_pk, result.status)
    # The status is the whole outcome — MATCHED, AMBIGUOUS, NO_MARKET and NO_MATCH mean
    # different things and `NO_MARKET` in particular is information about the ad, not an
    # absence of it. Returning it puts that distinction in the run log.
    return f"ad {ad_pk}: {result.status}"


def refresh_stale_reference_prices(limit: int | None = None) -> str:
    """Re-fetch price series for products something already linked, past their TTL.

    Wraps `manage.py lookup_reference_price --refresh-stale`: no resolution work, one
    price-trend call per product, so the history stays current without re-deciding what any
    ad is.
    """
    out = StringIO()
    kwargs: dict[str, object] = {"refresh_stale": True}
    if limit is not None:
        kwargs["limit"] = limit
    call_command("lookup_reference_price", stdout=out, **kwargs)
    summary = out.getvalue().strip().replace("\n", " | ") or "nothing stale"
    logger.info("Reference price refresh: %s", summary)
    return summary
