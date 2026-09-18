"""Re-fetching facts about one ad that has already been scraped.

The scrape walk sees an ad once and, apart from the delisting sweep's price check, never
looks at it again — `_resolve_ad` returns the existing row untouched on rediscovery. That
is right for the pipeline (it is optimising for latency across thousands of listings) and
wrong for the one listing somebody is actually looking at.

These are the "look again at this one" operations. They take an `Ad`, not a pk — the pk
boundary belongs to the task layer, so these stay callable from a shell, a test or a command
without a queue in the way.
"""
import logging
from dataclasses import dataclass

import requests

from bazos.delisting import SWEEPABLE_MARKETPLACES, apply_batch
from bazos.geo import ensure_postal_code, parse_postal_code
from bazos.models import Ad, AdSource, Marketplace
from bazos.scraping.bazos.bazos_api_scraper import BazosApiScraper, parse_listing_item
from bazos.scraping.query_runner import get_scraper

logger = logging.getLogger(__name__)


class NotRefreshable(Exception):
    """This marketplace has no cheap way to re-read one listing's row."""


def fetch_full_description(ad: Ad, session: requests.Session) -> Ad:
    """Fetch and store one ad's full description, whatever its marketplace.

    `Query.load_full_description` is a *per-query* boolean, so today the choice is "every ad
    on this query pays a detail request, or none do". Per-ad is the granularity that
    actually matches the question, which is always about one listing.

    On the API path this call is also the only source of `email_id`/`phone_id`, so it is
    what turns an ad with no seller into one that has ratings and partner ids to look up.
    """
    scraper = get_scraper(ad.marketplace, session)
    scraper.load_full_description(ad)
    ad.save()
    return ad


def refresh_ad(ad: Ad, session: requests.Session) -> str:
    """Re-read one listing's row: is it still up, and has anything about it moved?

    **Routes the payload through `apply_batch` rather than writing the price itself**, and
    that is the whole design. A price seen here is a price change like any other: it has to
    create a `PriceChange` row and flip every delivery of the ad to `PRICE_CHANGED`, or the
    append-only history silently loses an entry and a listing that dropped 30% is re-filtered
    against its pre-drop residual. Reusing the sweep's function means this cannot drift from
    it, and inherits its `None`-is-not-`{}` contract for free.

    ⚠️ **`view_count` is deliberately not refreshed.** The column means "views at the time of
    discovery" and two research documents reason about it on exactly that basis —
    `PC_PRICE_MODEL.md` and `MACBOOK_PRICE_MODEL.md` both note it correlates ~0.06 with age
    *because* it is captured once, making it a staleness measure rather than a demand one.
    Overwriting it in place would quietly convert every historical row to a different
    quantity. "Views now" is a genuinely useful second fact; it needs its own column and its
    own decision, not a silent redefinition of this one.

    Raises `NotRefreshable` for a marketplace with no bulk-id endpoint: Vinted and Sbazar
    would need a full detail fetch per ad, which is `fetch_full_description`'s job, not this
    one's.
    """
    if ad.marketplace not in SWEEPABLE_MARKETPLACES:
        raise NotRefreshable(
            f"{ad.marketplace} has no bulk-id endpoint; use fetch_full_description instead"
        )

    scraper = BazosApiScraper(session)
    found = scraper.fetch_by_ids([ad.external_id])
    if found is None:
        # Same contract as the sweep, and the reason it exists: `None` is "no usable answer"
        # and `{}` is "a successful response listed none of these". Conflating them wrote 180
        # false removals on 2026-09-17.
        raise RuntimeError(f"no usable response refreshing ad {ad.pk}")

    result = apply_batch([ad], found)
    row = found.get(ad.external_id)
    if row is None:
        return f"ad {ad.pk}: no longer listed"

    changed = _refresh_listing_facts(ad, row)
    suffix = f", refreshed {', '.join(changed)}" if changed else ""
    return (
        f"ad {ad.pk}: still listed"
        f"{', price changed' if result.price_changes else ''}{suffix}"
    )


def _refresh_listing_facts(ad: Ad, row: dict) -> list[str]:
    """Update the listing facts that are cheap, safe and currently frozen at discovery.

    `topped` and `url` only — see `refresh_ad` on why `view_count` is not here. Both are
    written with `update_fields` so this cannot race the price columns `apply_batch` just
    wrote on the same row.
    """
    changed = []
    topped = str(row.get("topped", "")).lower() == "true" or row.get("topped") is True
    if topped != ad.topped:
        ad.topped = topped
        changed.append("topped")
    url = row.get("url")
    if url and url != ad.url:
        ad.url = url
        changed.append("url")
    if changed:
        ad.save(update_fields=changed)
    return changed


@dataclass(frozen=True)
class InventoryResult:
    fetched: int = 0
    created: int = 0
    already_known: int = 0

    def __str__(self) -> str:
        return f"{self.fetched} listed, {self.created} new, {self.already_known} already known"


def fetch_seller_listings(publisher, session: requests.Session) -> InventoryResult:
    """Pull one seller's entire current inventory and store what we do not already have.

    `ads.php?email_id=` / `phone_id=` returns the lot in one request (HIDDEN_API.md §6.4g),
    which is what makes "what else is this person selling" affordable at all.

    **Rows are written as `Marketplace.BAZOS`, not `BAZOS_API`**, and that is the detail to
    get right. `Ad` is unique on `(marketplace, external_id)`, so writing the API's own
    marketplace value would create a *second* row for a listing the HTML scraper has already
    seen, or will see tomorrow — two rows for one real-world ad, each with half its history,
    both swept for delisting. The transport used to fetch a listing is not a property of the
    listing.

    Each new row is stamped `source=SELLER_SWEEP` and gets **no `AdDelivery`** — no query
    asked for it, and inventing one would put ads nobody searched for into a notification
    stream. The provenance column is what keeps "ads we have" and "ads our queries found"
    tellable apart afterwards.

    The publisher FK is set from the id we queried, which is the one seller fact the thin
    payload does not carry and we already know for certain.
    """
    scraper = BazosApiScraper(session)
    rows = scraper.fetch_publisher_listings(publisher.ratings_param, publisher.bazos_id)
    if rows is None:
        raise RuntimeError(
            f"no usable inventory response for {publisher.ratings_param}={publisher.bazos_id}"
        )

    fk = "email_publisher" if publisher.ratings_param == "email_id" else "phone_publisher"
    created = already = 0
    for row in rows:
        parsed = parse_listing_item(row)
        if Ad.objects.filter(
            marketplace=Marketplace.BAZOS, external_id=parsed["external_id"]
        ).exists():
            already += 1
            continue
        ad = Ad.objects.create(
            marketplace=Marketplace.BAZOS,
            source=AdSource.SELLER_SWEEP,
            short_description="",   # the thin listing payload carries none
            publisher_name="",
            **{fk: publisher},
            **parsed,
        )
        ensure_postal_code(parse_postal_code(ad.location), session)
        created += 1

    return InventoryResult(fetched=len(rows), created=created, already_known=already)
