import logging
from contextlib import contextmanager

import requests
from django.db import DatabaseError

from bazos.const import NEW_PRODUCT_LOAD_MAX
from bazos.geo import ensure_postal_code, parse_postal_code
from bazos.models import Ad, AdDelivery, AdStatus, Marketplace, PriceChange, Query
from bazos.scraping.bazos.bazos_api_scraper import BazosApiScraper
from bazos.scraping.bazos.bazos_scraper import BazosScraper
from bazos.scraping.marketplace import MarketplaceScraper
from bazos.scraping.sbazar.sbazar_scraper import SbazarScraper
from bazos.scraping.vinted.vinted_scraper import VintedScraper

logger = logging.getLogger(__name__)


def _build_scrapers(session: requests.Session) -> dict[str, MarketplaceScraper]:
    return {
        Marketplace.BAZOS.value: BazosScraper(session),
        Marketplace.BAZOS_API.value: BazosApiScraper(session),
        Marketplace.VINTED.value: VintedScraper(session),
        Marketplace.SBAZAR.value: SbazarScraper(session),
    }


def get_scraper(marketplace: str, session: requests.Session) -> MarketplaceScraper:
    return _build_scrapers(session)[marketplace]


class QueryRunner:
    def __init__(self, query: Query, session: requests.Session):
        self.query = query
        self.session = session
        self.scraper: MarketplaceScraper = get_scraper(query.marketplace, session)
        self.new_product_counter = 0
        self.rows_seen_counter = 0

    def _get_known_delivery(self, product: Ad) -> AdDelivery | None:
        """Has THIS query already seen this listing? Keys the dedup break."""
        return (
            AdDelivery.objects
            .filter(
                query=self.query,
                ad__marketplace=product.marketplace,
                ad__external_id=product.external_id,
            )
            .select_related("ad")
            .first()
        )

    def _resolve_ad(self, product: Ad) -> Ad:
        """Global listing identity, shared across queries."""
        existing = Ad.objects.filter(
            marketplace=product.marketplace, external_id=product.external_id
        ).first()
        if existing is not None:
            return existing
        product.save()
        # Resolve the ad's postal code here, not in run_filter, for two reasons: this is
        # the process that owns a Tor session and knows how to pace, and doing it before
        # the delivery row exists means the filter never races a half-warmed cache. Almost
        # always a cache hit and no request at all — a query's ads come from a small,
        # quickly-saturated set of postal codes. Unpaced on purpose: the miss is rare and
        # the surrounding walk is already spaced.
        ensure_postal_code(parse_postal_code(product.location), self.session)
        return product

    def _handle_new_product(self, product: Ad):
        """This query has found a listing it doesn't have a delivery for yet.

        Resolves/creates the global Ad, fetches its full description if it's still missing
        — gated on the description, not on "did this query discover the ad first": a query
        with load_full_description=True must not go without it forever just because a
        different, non-fetching query happened to find the ad first — and creates this
        query's PENDING delivery.

        Idempotent via get_or_create: a `run_new_query` pass interrupted mid-pagination
        (blacklist hit, a raise from `load_full_description`, SIGTERM) leaves partial rows
        behind with no wrapping transaction, and the next pass replays from page 1. Without
        get_or_create, the replay's second `AdDelivery` for an already-delivered ad violates
        `unique_delivery_per_ad_query` and the query is wedged forever, raising the same
        IntegrityError every pass.
        """
        ad = self._resolve_ad(product)
        if self.query.load_full_description and ad.full_description is None:
            self.scraper.load_full_description(ad)
            ad.save()
        _, created = AdDelivery.objects.get_or_create(
            ad=ad, query=self.query, defaults={"status": AdStatus.PENDING}
        )
        if created:
            logger.info("New product %s", product)
            self.new_product_counter += 1

    @contextmanager
    def _tolerating_one_bad_ad(self, product: Ad):
        """Let a single unusable listing be skipped instead of killing the whole walk.

        Without this, one malformed row aborts the query for the entire pass — and since
        the marketplace keeps serving it, for every pass after that too. A `varchar(300)`
        overflow on `short_description` wedged the `audeze` query for two hours this way
        on 2026-08-23. That column is fixed, but the shape recurs: every field here is
        scraped free text against a `max_length` nobody measured.

        Catches `DatabaseError` and **nothing wider**. That is exactly what this guard is
        for, and a wider net silently reclassifies real failures as bad data:
        `load_full_description` can raise `requests.ConnectionError`, which
        `BazosScraper.run_request` does not handle (it catches only `TimeoutException`
        and `URLError`, and `requests.ConnectionError` is neither). Swallowing that let a
        dead detail-fetch transport finish the walk with `success=True` and zero new ads,
        landing in the canary's "quiet market or dedup drift" bucket — a WARNING at a
        high threshold — instead of failing loudly. `InterfaceError` is left out for the
        same reason: a broken connection is transport, not a bad ad.

        `MarketplaceBlockedError` needs no special case now — it is not a `DatabaseError`,
        so it propagates on its own, which is what the runner needs to rotate the IP.

        There is deliberately **no `transaction.atomic()`** here. The walk runs in
        autocommit, so a failed statement is self-contained and there is nothing to roll
        back to. Wrapping it was actively harmful: with no enclosing atomic it opened a
        *real* transaction, not a savepoint (measured: `in_atomic_block=True`,
        `savepoint_ids=[]`), and held it open across `load_full_description`'s
        1–3 s sleep plus its Tor GETs — pinning the new Ad's row lock and its
        `(marketplace, external_id)` index-insertion lock for the whole fetch, up to
        NEW_PRODUCT_LOAD_MAX times in a backfill, and blocking autovacuum behind the
        oldest open transaction.

        If this walk is ever wrapped in `atomic()` (the job-queue proposal would), this
        guard needs a savepoint **and** the network fetch must be hoisted out of it first.
        Those two go together; doing only the first reintroduces the problem above.
        """
        try:
            yield
        except DatabaseError:
            logger.exception(
                "Skipping unusable ad %s on query %s", product.external_id, self.query
            )

    def run_new_query(self):
        self.query.new_query = False

        counter = 0
        for product in self.scraper.run_query(self.query):
            self.rows_seen_counter += 1
            if not product.topped:
                counter += 1
                if counter >= NEW_PRODUCT_LOAD_MAX:
                    break

            with self._tolerating_one_bad_ad(product):
                if self.query.ignore_first_run:
                    ad = self._resolve_ad(product)
                    # get_or_create, not create: same replay hazard as _handle_new_product
                    # — an interrupted-then-replayed backfill pass must not re-raise on a
                    # product this query already suppressed.
                    AdDelivery.objects.get_or_create(
                        ad=ad, query=self.query, defaults={"status": AdStatus.SUPPRESSED}
                    )
                else:
                    self._handle_new_product(product)

    def run_existing_query(self):
        """Walk newest→oldest, stopping once the query is confident it has caught up.

        "Confident" means `scraper.dedup_break_streak` consecutive already-known,
        non-topped ads in a row (default 1 — stop at the very first one, the original
        behaviour). A single hit is only a safe stopping signal when the scraper's
        default ordering is by creation time, so that everything below the first known
        ad is provably older than everything above it. Bazos and Vinted rely on exactly
        that and don't override the attribute. Sbazar does not satisfy it: its default
        order is `sorting_date` (~= edit time), so an old, already-known ad can resurface
        above genuinely new listings just because it was edited recently — see
        docs/research/marketplaces/SBAZAR.md §5b.4 and docs/archive/shipped/SBAZAR_SCRAPER.md §11.
        SbazarScraper sets a higher streak so the walk tolerates that interleaving
        instead of giving up on the first stale-looking hit. Whatever the streak, the
        walk is still bounded by the scraper's own max-pages safety net.
        """
        dedup_break_streak = getattr(self.scraper, "dedup_break_streak", 1)
        known_streak = 0
        for product in self.scraper.run_query(self.query):
            self.rows_seen_counter += 1
            known_delivery = self._get_known_delivery(product)
            if known_delivery is None:
                known_streak = 0
                with self._tolerating_one_bad_ad(product):
                    self._handle_new_product(product)
                continue

            known_ad = known_delivery.ad
            # The guard wraps only the fragile writes, never the streak/break bookkeeping
            # below: a skipped ad must not also cost the walk its stopping condition.
            if known_ad.price_raw != product.price_raw:
                with self._tolerating_one_bad_ad(product):
                    logger.info(
                        "Price changed for ad %d: %s -> %s",
                        known_ad.pk, known_ad.price_raw, product.price_raw,
                    )
                    PriceChange.objects.create(
                        ad=known_ad,
                        old_price=known_ad.price_raw,
                        new_price=product.price_raw,
                        old_price_amount=known_ad.price,
                        new_price_amount=product.price,
                    )
                    known_ad.price_raw = product.price_raw
                    known_ad.price = product.price
                    known_ad.price_type = product.price_type
                    known_ad.save(update_fields=["price_raw", "price", "price_type"])
                    # A price change is a fact about the AD — every query watching it
                    # re-enters the filter. Unconditional, matching pre-split behaviour
                    # (including un-suppressing a SUPPRESSED delivery — see
                    # AD_DELIVERY_SPLIT.md §3.2).
                    AdDelivery.objects.filter(ad=known_ad).update(status=AdStatus.PRICE_CHANGED)
            logger.debug("Product already exists %s", known_ad)
            if product.topped:
                logger.debug("TOP product — continuing")
                continue

            known_streak += 1
            if known_streak >= dedup_break_streak:
                logger.debug("%d consecutive known ads — breaking", known_streak)
                break

    def run(self) -> int:
        if self.query.new_query:
            logger.info("Running NEW query %s", self.query)
            self.run_new_query()
        else:
            logger.info("Running EXISTING query %s", self.query)
            self.run_existing_query()

        return self.new_product_counter
