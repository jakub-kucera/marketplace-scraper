import logging
import requests

from bazos.const import NEW_PRODUCT_LOAD_MAX
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


class BazosQueryRunner:
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

    def _resolve_ad(self, product: Ad) -> tuple[Ad, bool]:
        """Global listing identity, shared across queries. Returns (ad, is_new_ad)."""
        existing = Ad.objects.filter(
            marketplace=product.marketplace, external_id=product.external_id
        ).first()
        if existing is not None:
            return existing, False
        product.save()
        return product, True

    def _handle_new_product(self, product: Ad):
        """This query has found a listing it doesn't have a delivery for yet.

        Resolves/creates the global Ad, fetches its full description only when nobody
        has seen it before (a second query rediscovering a known listing must not re-pay
        for the detail request), and creates this query's PENDING delivery.
        """
        logger.info("New product %s", product)
        self.new_product_counter += 1
        ad, is_new_ad = self._resolve_ad(product)
        if is_new_ad and self.query.load_full_description:
            self.scraper.load_full_description(ad)
            ad.save()
        AdDelivery.objects.create(ad=ad, query=self.query, status=AdStatus.PENDING)

    def run_new_query(self):
        self.query.new_query = False

        counter = 0
        for product in self.scraper.run_query(self.query):
            self.rows_seen_counter += 1
            if not product.topped:
                counter += 1
                if counter >= NEW_PRODUCT_LOAD_MAX:
                    break

            if self.query.ignore_first_run:
                ad, _ = self._resolve_ad(product)
                AdDelivery.objects.create(ad=ad, query=self.query, status=AdStatus.SUPPRESSED)
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
        docs/marketplaces/SBAZAR.md §5b.4 and docs/refactor/STAGE9_SBAZAR_SPEC.md §11.
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
                self._handle_new_product(product)
                continue

            known_ad = known_delivery.ad
            if known_ad.price_raw != product.price_raw:
                logger.info(
                    "Price changed for ad %d: %s -> %s", known_ad.pk, known_ad.price_raw, product.price_raw
                )
                PriceChange.objects.create(
                    ad=known_ad,
                    old_price=known_ad.price_raw,
                    new_price=product.price_raw,
                )
                known_ad.price_raw = product.price_raw
                known_ad.save(update_fields=["price_raw"])
                # A price change is a fact about the AD — every query watching it re-enters
                # the filter. Unconditional, matching pre-split behaviour (including
                # un-suppressing a SUPPRESSED delivery — see AD_DELIVERY_SPLIT_SPEC.md §3.2).
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
