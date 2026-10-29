"""Batch and scripting entry point for reference-price lookup.

**Explicit by construction.** Nothing schedules this; it is run by a person, or by a
`--refresh-stale` invocation that only re-reads products already linked. It must never be
called from `run_scraper`/`run_filter`/`run_sender` — it performs network I/O, and
`run_filter` holds row locks while its rules run.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError

from marketplace.models import Ad
from refprice.models import LookupStatus, RefProduct, RefProductLink
from refprice.providers.base import get_provider
from refprice.results import ReferenceRequest
from refprice.services import DEFAULT_TTL, lookup_reference_price


class Command(BaseCommand):
    help = "Look up a new-price reference for one ad, a query's ads, or stale products."

    def add_arguments(self, parser):
        target = parser.add_mutually_exclusive_group(required=True)
        target.add_argument("--ad", type=int, help="One Ad pk.")
        target.add_argument("--query", type=int, help="Ads delivered for one Query pk.")
        target.add_argument("--refresh-stale", action="store_true",
                            help="Re-fetch already-linked products past their TTL.")
        parser.add_argument("--limit", type=int, default=20)
        parser.add_argument("--provider", default="zbozi")
        parser.add_argument("--dry-run", action="store_true",
                            help="Resolve and print; write nothing.")

    def handle(self, *args, **options):
        provider = get_provider(options["provider"])

        if options["refresh_stale"]:
            return self._refresh_stale(provider, options)

        ads = self._targets(options)
        if not ads:
            self.stdout.write(self.style.WARNING("No ads matched."))
            return

        counts: dict[str, int] = {}
        for ad in ads:
            result = lookup_reference_price(
                ReferenceRequest(title=ad.name, description=ad.short_description or ""),
                ad=ad,
                provider=provider,
                persist=not options["dry_run"],
                use_cache=not options["dry_run"],
            )
            counts[result.status] = counts.get(result.status, 0) + 1
            self._report(ad, result)

        self.stdout.write("")
        for status, count in sorted(counts.items()):
            self.stdout.write(f"  {count:>4}  {status}")
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("\nDry run — nothing was written."))

    def _targets(self, options) -> list[Ad]:
        if options["ad"]:
            try:
                return [Ad.objects.get(pk=options["ad"])]
            except Ad.DoesNotExist:
                raise CommandError(f"No Ad with pk={options['ad']}") from None
        return list(
            Ad.objects.filter(deliveries__query_id=options["query"])
            .distinct().order_by("-created")[: options["limit"]]
        )

    def _refresh_stale(self, provider, options) -> None:
        """Only touches products something already linked — one price-trend call each,
        no resolution work, so the series stays current for free."""
        cutoff = dt.timedelta(days=DEFAULT_TTL.days)
        stale = [
            p for p in RefProduct.objects.filter(
                provider=options["provider"], links__isnull=False
            ).distinct()[: options["limit"]]
            if not p.is_fresh(cutoff)
        ]
        if not stale:
            self.stdout.write(self.style.SUCCESS("Nothing stale."))
            return

        for product in stale:
            link = RefProductLink.objects.filter(product=product).first()
            if link is None or link.ad is None:
                continue
            result = lookup_reference_price(
                ReferenceRequest(title=link.ad.name), ad=link.ad, provider=provider,
                use_cache=False,
            )
            self.stdout.write(f"  refreshed {product.name[:48]:48s} {result.status}")

    def _report(self, ad: Ad, result) -> None:
        head = f"{ad.pk:>7}  {ad.name[:44]:44s}"
        if result.status == LookupStatus.MATCHED and result.pricing:
            trend = result.history.trend if result.history else "?"
            self.stdout.write(self.style.SUCCESS(
                f"{head} -> {result.product.name[:34]:34s} "
                f"median {result.pricing.median_czk:>7,} Kč  "
                f"{result.pricing.shop_count:>2} shops  {trend}"
            ))
        elif result.status == LookupStatus.NO_MARKET and result.product:
            self.stdout.write(self.style.WARNING(
                f"{head} -> {result.product.name[:34]:34s} discontinued (too few shops)"
            ))
        else:
            detail = result.detail or (
                result.match.candidates_considered[0].reason
                if result.match.candidates_considered else "no candidates"
            )
            self.stdout.write(f"{head} -> {result.status}: {detail[:48]}")
