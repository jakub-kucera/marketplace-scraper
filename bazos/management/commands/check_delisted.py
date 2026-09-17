"""Sweep live ads to find out which have disappeared, and when.

This is the only thing in the project that records an *outcome* rather than an asking price.
See `bazos/delisting.py` for what the numbers mean and, more importantly, what they do not.

Cost, which is the whole reason the schedule exists: `ads.php?ad_id[]=` takes 210 ids per
request, so a complete sweep of ~20k live Bazos ads is ~96 requests. Checking everything
hourly would be ~3 300/day — about three times the entire current scrape. The age-decayed
schedule in `DELIST_SCHEDULE` covers the same ads for ~33/day.

Deliberately **not** a `Job` (see docs/proposals/JOB_QUEUE.md): one recurring command does
not justify that machinery, and the repo has been bitten by premature generality before.
Deliberately **no** `select_for_update` either — that idiom exists in `run_filter`/`run_sender`
because they are competing pollers, and this is a single periodic sweep with no second worker.
"""
import logging
from random import uniform
from time import sleep

from django.conf import settings
from django.core.management.base import BaseCommand

from bazos.const import DELIST_BATCH_SIZE, DELIST_WAIT_TIME, MAX_BLACKLIST_RETRIES
from bazos.delisting import SweepResult, apply_batch, due_for_check
from bazos.exceptions import MarketplaceBlockedError
from bazos.scraping.bazos.bazos_api_scraper import BazosApiScraper
from ip_changer.dummy import DummyIPChanger
from ip_changer.ip_changer import IPChanger
from ip_changer.tor import TorIPChanger

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Check which listings have disappeared, recording last_seen_at / removed_at."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit", type=int, default=None,
            help="Stop after this many ads (default: everything due).",
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what is due without making any request or writing anything.",
        )

    def handle(self, *args, **options):
        due = due_for_check()
        if options["limit"]:
            due = due[: options["limit"]]
        ads = list(due)

        batches = (len(ads) + DELIST_BATCH_SIZE - 1) // DELIST_BATCH_SIZE
        self.stdout.write(f"{len(ads)} ads due, {batches} request(s) of up to {DELIST_BATCH_SIZE}")
        if options["dry_run"] or not ads:
            return

        changer = self._ip_changer()
        assert changer.session is not None
        scraper = BazosApiScraper(changer.session)
        total = SweepResult()

        for index in range(0, len(ads), DELIST_BATCH_SIZE):
            batch = ads[index : index + DELIST_BATCH_SIZE]
            if index:
                sleep(uniform(*DELIST_WAIT_TIME))
            found, ok = self._fetch_with_rotation(scraper, changer, batch)
            if not ok:
                # Skipped, NOT recorded as removed. A blocked or broken request is an
                # absence of information; treating it as evidence would write false deaths
                # into the only outcome data this project has.
                total = _merge(total, SweepResult(batches_failed=1))
                continue
            total = _merge(total, apply_batch(batch, found))

        self.stdout.write(self.style.SUCCESS(str(total)) if not total.batches_failed
                          else self.style.WARNING(str(total)))

    # -- transport --------------------------------------------------------

    def _ip_changer(self) -> IPChanger:
        changer_class = DummyIPChanger if settings.IP_CHANGER_TYPE == "DUMMY" else TorIPChanger
        return changer_class()

    def _fetch_with_rotation(self, scraper, changer: IPChanger, batch) -> tuple[dict, bool]:
        """One batch, rotating the circuit on a 403. `(found, ok)` — `ok` False means skip.

        Same shape as `ScrapeRunner._run_query_with_rotation` and `geocode_postal_codes`:
        a block is a property of the exit IP, so without rotating, one bad circuit fails
        every remaining batch identically.
        """
        ids = [ad.external_id for ad in batch]
        for attempt in range(1, MAX_BLACKLIST_RETRIES + 1):
            try:
                scraper.session = changer.session
                found = scraper.fetch_by_ids(ids)
            except MarketplaceBlockedError as e:
                logger.warning(
                    "Delisting batch blocked on exit %s (attempt %d/%d)",
                    e.exit_ip or "unknown", attempt, MAX_BLACKLIST_RETRIES,
                )
                if not changer.rotate_circuit():
                    return {}, False
                continue
            # None is "no usable answer", NOT "none of them are listed". A timed-out or
            # unparseable response must record nothing — writing `{}` here would mark all
            # 210 ads in the batch as removed, which is what happened in production on
            # 2026-09-17 against a Tor circuit that had not finished warming up.
            if found is None:
                logger.warning("Delisting batch got no usable response; skipping %d ads", len(ids))
                return {}, False
            return found, True
        return {}, False


def _merge(a: SweepResult, b: SweepResult) -> SweepResult:
    return SweepResult(
        checked=a.checked + b.checked,
        still_listed=a.still_listed + b.still_listed,
        newly_removed=a.newly_removed + b.newly_removed,
        price_changes=a.price_changes + b.price_changes,
        batches_failed=a.batches_failed + b.batches_failed,
    )
