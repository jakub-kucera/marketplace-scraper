"""Undo the removals the mis-paginated sweep invented, by re-checking them.

`fetch_by_ids` shipped without a `limit`, so `ads.php` answered each 210-id batch with its
default 30 rows and `apply_batch` wrote the 180 absent ids as removed. 19 008 rows carry a
`removed_at` written that way; re-checking 200 of them at random against the live API on
2026-09-19 found 112 still listed, a 56% false rate.

**The false and the genuine removals are indistinguishable in the database.** The response
that produced them is gone, and nothing recorded which ids the payload actually accounted
for, so there is no query that separates "absent because delisted" from "absent because the
page ended". The only way to tell is to ask again, which is what this does.

Re-checking is cheap - one request per 210 ads, so the whole repair is ~91 requests - which
is why this re-derives the truth rather than blanket-clearing the column. A blanket clear
would also discard the genuine removals, and those are the observations worth keeping.

It cannot be run against the broken scraper, and not by checking: this command was added in
the same commit as the `limit` fix, so a deployment that has one has the other. There is no
response-shape test that would work anyway - a short page and a batch of genuinely dead ads
produce byte-identical payloads, which is the whole reason the corruption was invisible.

Idempotent: a second run re-checks the same ads and finds nothing left to change. Ads still
absent keep the `removed_at` they already have, because their original timestamp is a better
estimate of when they went than now() is.
"""
import logging
from random import uniform
from time import sleep

from django.core.management.base import BaseCommand
from django.utils import timezone

from bazos.const import DELIST_BATCH_SIZE, DELIST_WAIT_TIME
from bazos.delisting import SWEEPABLE_MARKETPLACES
from bazos.models import Ad
from bazos.scraping.bazos.bazos_api_scraper import BazosApiScraper
from bazos.scraping.session import AllCircuitsBlocked, build_ip_changer, with_rotation

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Re-check ads marked removed and clear the ones that are still listed."

    def add_arguments(self, parser):
        parser.add_argument(
            "--since", default=None,
            help="Only ads whose removed_at is on or after this ISO date (e.g. 2026-09-17).",
        )
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Stop after this many ads. Use to rehearse on a small slice first.",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Make the requests and report the split, writing nothing.",
        )

    def handle(self, *args, **options):
        ads = self._candidates(options)
        if not ads:
            self.stdout.write("nothing to re-check")
            return

        batches = (len(ads) + DELIST_BATCH_SIZE - 1) // DELIST_BATCH_SIZE
        self.stdout.write(f"{len(ads)} ads marked removed, {batches} request(s) of up to {DELIST_BATCH_SIZE}")

        changer = build_ip_changer()
        assert changer.session is not None
        scraper = BazosApiScraper(changer.session)

        still_listed: list[int] = []
        confirmed_gone = 0
        failed_batches = 0

        for index in range(0, len(ads), DELIST_BATCH_SIZE):
            batch = ads[index : index + DELIST_BATCH_SIZE]
            if index:
                sleep(uniform(*DELIST_WAIT_TIME))
            found = self._fetch(scraper, changer, batch)
            if found is None:
                # Same contract as the sweep: no usable answer is not evidence. Leaving the
                # row as it is keeps a possibly-false removal, which is the conservative
                # direction here - a later run can still repair it.
                failed_batches += 1
                continue
            alive = [ad.pk for ad in batch if ad.external_id in found]
            still_listed.extend(alive)
            confirmed_gone += len(batch) - len(alive)

        self._report(len(ads), len(still_listed), confirmed_gone, failed_batches)
        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("dry run: nothing written"))
            return

        if still_listed:
            now = timezone.now()
            updated = Ad.objects.filter(pk__in=still_listed).update(removed_at=None, last_seen_at=now)
            self.stdout.write(self.style.SUCCESS(f"cleared removed_at on {updated} ads"))

    # -- helpers ----------------------------------------------------------

    def _candidates(self, options) -> list[Ad]:
        qs = Ad.objects.filter(
            removed_at__isnull=False, marketplace__in=SWEEPABLE_MARKETPLACES
        ).order_by("pk")
        if options["since"]:
            qs = qs.filter(removed_at__date__gte=options["since"])
        if options["limit"]:
            qs = qs[: options["limit"]]
        return list(qs)

    def _fetch(self, scraper, changer, batch) -> dict | None:
        ids = [ad.external_id for ad in batch]

        def fetch(session):
            scraper.session = session
            return scraper.fetch_by_ids(ids)

        try:
            return with_rotation(changer, fetch, what=f"Repair batch of {len(ids)}")
        except AllCircuitsBlocked:
            return None

    def _report(self, checked: int, alive: int, gone: int, failed: int) -> None:
        share = f"{100 * alive / checked:.1f}%" if checked else "n/a"
        line = (
            f"checked {checked}, still listed {alive} ({share} were false removals), "
            f"confirmed gone {gone}, failed batches {failed}"
        )
        self.stdout.write(self.style.SUCCESS(line) if not failed else self.style.WARNING(line))
