import logging
from datetime import datetime, timezone
from pathlib import Path
from random import uniform
from time import sleep

from bazos.exceptions import BazosBlacklistedError
from bazos.models import Query, QueryRun
from bazos.scraping.bazos_query_runner import BazosQueryRunner, get_scraper
from bazos.scraping.interval_multiplier import NightMultiplier
from django.conf import settings

from ip_changer.dummy import DummyIPChanger
from ip_changer.tor import TorIPChanger
from senders.models import Discord
from senders.services.discord_sender import DiscordSender

logger = logging.getLogger(__name__)


class BazosRunner:

    def __init__(self):
        discord_loggers = Discord.objects.filter(for_logging=True)
        self.interval_multiplier = NightMultiplier()
        self.discord_loggers = [DiscordSender.from_model(s) for s in discord_loggers]
        ip_changer_class = DummyIPChanger if settings.IP_CHANGER_TYPE == "DUMMY" else TorIPChanger
        self.ip_changer = ip_changer_class(skip_1st_renew=False)
        self.zero_rows_passes = 0
        self.zero_new_ads_passes = 0

    def run(self):
        while True:
            self.log(f"Waking up at {datetime.utcnow()} UTC")
            Query.objects.filter(randomly_generated=True).update(enabled=False)
            queries = Query.objects.filter(enabled=True).order_by('?')

            start = datetime.now(timezone.utc)
            pass_rows_seen = 0
            pass_new_ads = 0
            successful_queries = 0
            for query in queries:
                self.log(f"running query {query}")

                blacklist_check = self._blacklist_checker(query)
                if blacklist_check(query.url):
                    self.log("IP got BLACKLISTED, attempting to change", level=logging.WARNING)
                    try:
                        self.change_ip(query, blacklist_check)
                    except BazosBlacklistedError:
                        logger.exception("Query %s still blacklisted after IP rotation attempts, skipping", query)
                        continue

                if self.ip_changer.check_ip_local():
                    self.log("WARNING: IP IS LOCAL", level=logging.WARNING)
                    continue

                query_run = QueryRun(
                    query=query,
                    run_start=datetime.now(timezone.utc),
                )
                query_run.save()
                try:
                    assert self.ip_changer.session is not None
                    query_runner = BazosQueryRunner(query, self.ip_changer.session)
                    new_products_count = query_runner.run()
                    query.save()
                    query_run.new_ads_count = new_products_count
                    pass_rows_seen += query_runner.rows_seen_counter
                    pass_new_ads += new_products_count
                    successful_queries += 1
                except Exception as e:
                    query_run.success = False
                    query_run.error = f"{type(e).__name__}: {e}"
                    logger.exception("Query %s failed", query)
                    continue
                finally:
                    query_run.run_end = datetime.now(timezone.utc)
                    query_run.save()
                logger.info("Found %d new products for query %s", new_products_count, query)

            end = datetime.now(timezone.utc)
            self.log(f"Finished running {len(queries)} queries in {end - start}. End time: {end}")
            self._check_zero_results_canary(pass_rows_seen, pass_new_ads, successful_queries)
            sleep_interval = self.get_next_interval()
            self.log(f"sleeping for {sleep_interval}")
            self._interruptible_sleep(sleep_interval)

    def get_next_interval(self):
        multiplier = self.interval_multiplier.get_current_multiplier()
        return multiplier * uniform(settings.INTERVAL_LOWER, settings.INTERVAL_UPPER)

    def _interruptible_sleep(self, total_seconds: float) -> None:
        """Sleep in short ticks, waking early if the force-run flag file is set."""
        tick = 5.0  # seconds between flag checks
        elapsed = 0.0
        flag_path = Path(settings.FORCE_RUN_FLAG_PATH)
        while elapsed < total_seconds:
            sleep(min(tick, total_seconds - elapsed))
            elapsed += tick
            if flag_path.exists():
                self.log("Force-run flag detected — skipping remaining sleep")
                flag_path.unlink(missing_ok=True)
                return

    def _check_zero_results_canary(self, rows_seen: int, new_ads: int, successful_queries: int) -> None:
        """Alert when the pipeline stops producing — parser drift looks exactly like a quiet market.

        Never fatal: a genuinely dead category at 3am must not stop the scraper.
        """
        if successful_queries == 0:
            # No query completed, so this pass carries no evidence either way. Those failures
            # are already loud via QueryRun.success and logger.exception — don't double-alert,
            # and don't let a crash storm masquerade as parser drift.
            return

        if rows_seen == 0:
            self.zero_rows_passes += 1
            if self.zero_rows_passes >= settings.ZERO_ROWS_ALERT_THRESHOLD:
                self.log(
                    f"CANARY: {self.zero_rows_passes} consecutive passes parsed ZERO rows across "
                    f"{successful_queries} successful queries — the scraper is probably broken "
                    f"(parser drift / blocked transport), not the market being quiet.",
                    level=logging.ERROR,
                )
                self.zero_rows_passes = 0
            # A zero-rows pass isn't a "rows parsed but zero new ads" pass — it's not evidence
            # for the quiet-market signal at all, so don't let it count toward that streak either.
            self.zero_new_ads_passes = 0
            return

        self.zero_rows_passes = 0

        if new_ads == 0:
            self.zero_new_ads_passes += 1
            if self.zero_new_ads_passes >= settings.ZERO_NEW_ADS_ALERT_THRESHOLD:
                self.log(
                    f"CANARY: {self.zero_new_ads_passes} consecutive passes found zero NEW ads "
                    f"({rows_seen} rows parsed, so scraping itself works) — either a quiet market "
                    f"or dedup drift.",
                    level=logging.WARNING,
                )
                self.zero_new_ads_passes = 0
        else:
            self.zero_new_ads_passes = 0

    def log(self, message: str, level: int = logging.INFO):
        logger.log(level, message)
        for discord_logger in self.discord_loggers:
            discord_logger.send_plain(message)

    def change_ip(self, query: Query, is_blacklisted=None):
        self.log(f"Changing IP, current={self.ip_changer.get_current_ip()}")
        new_ip = self.ip_changer.renew_ip_bazos_ok(query.url, is_blacklisted=is_blacklisted)
        self.log(f"NEW IP={new_ip}")

    def _blacklist_checker(self, query: Query):
        def check(url: str) -> bool:
            assert self.ip_changer.session is not None
            return get_scraper(query.marketplace, self.ip_changer.session).check_blacklisted()
        return check

