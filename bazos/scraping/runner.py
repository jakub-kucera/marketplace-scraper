import logging
from datetime import datetime, timezone
from ipaddress import ip_address
from pathlib import Path
from random import uniform
from time import sleep

from bazos.const import MAX_BLACKLIST_RETRIES, QUERY_WAIT_TIME
from bazos.exceptions import MarketplaceBlockedError
from bazos.models import Query, QueryRun
from bazos.scraping.query_runner import QueryRunner
from bazos.scraping.interval_multiplier import NightMultiplier
from django.conf import settings

from ip_changer.dummy import DummyIPChanger
from ip_changer.tor import TorIPChanger
from senders.models import Discord
from senders.services.discord_sender import DiscordSender

logger = logging.getLogger(__name__)


class ScrapeRunner:

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
            if self.ip_changer.check_ip_local():
                # Once per pass, not once per query: it is a property of the transport,
                # not of the query, and each check costs an icanhazip round-trip.
                self.log("WARNING: IP IS LOCAL, skipping this pass", level=logging.WARNING)
            else:
                self._run_pass()
            sleep_interval = self.get_next_interval()
            self.log(f"sleeping for {sleep_interval}")
            self._interruptible_sleep(sleep_interval)

    def _run_pass(self) -> None:
        Query.objects.filter(randomly_generated=True).update(enabled=False)
        queries = Query.objects.filter(enabled=True).order_by('?')

        start = datetime.now(timezone.utc)
        pass_rows_seen = 0
        pass_new_ads = 0
        successful_queries = 0
        for index, query in enumerate(queries):
            if index:
                self._sleep_between_queries()
            self.log(f"running query {query}")

            result = self._run_query_with_rotation(query)
            if result is None:
                continue
            rows_seen, new_ads = result
            pass_rows_seen += rows_seen
            pass_new_ads += new_ads
            successful_queries += 1
            logger.info("Found %d new products for query %s", new_ads, query)

        end = datetime.now(timezone.utc)
        self.log(f"Finished running {len(queries)} queries in {end - start}. End time: {end}")
        self._check_zero_results_canary(pass_rows_seen, pass_new_ads, successful_queries)

    def _run_query_with_rotation(self, query: Query) -> tuple[int, int] | None:
        """Run one query, rotating the IP and retrying when the marketplace 403s the *real*
        request.

        Returns ``(rows_seen, new_ads)``, or ``None`` if the query produced nothing usable
        this pass (blacklisted on every attempt, or any other failure).

        There is deliberately **no pre-flight ``check_blacklisted()`` probe**. It cost one
        full search request per query and answered the wrong question: it always hit the
        single fixed `BAZOS_BLACKLIST_CHECK_URL`, but the block is path-scoped, so it kept
        reporting "clear" moments before the query's own page returned 403. Every
        `MarketplaceBlockedError` in the QueryRun history of 2026-08-23 is a run whose probe
        had just passed. A 200 on the query's own URL is the only evidence that this IP can
        reach this path, so **the attempt is the probe** — and unlike the probe it costs
        nothing extra, because it is a request we wanted to make anyway.

        Previously a 403 here fell into the generic `except Exception` below, was written
        off, and the loop moved to the next query on the *same* dead IP milliseconds later
        — which is why the failures arrive in clusters rather than singly.
        """
        for attempt in range(1, MAX_BLACKLIST_RETRIES + 1):
            query_run = QueryRun(
                query=query,
                run_start=datetime.now(timezone.utc),
                exit_ip=self._current_exit_ip(),
            )
            query_run.save()
            try:
                assert self.ip_changer.session is not None
                query_runner = QueryRunner(query, self.ip_changer.session)
                new_products_count = query_runner.run()
                query.save()
                query_run.new_ads_count = new_products_count
                return query_runner.rows_seen_counter, new_products_count
            except MarketplaceBlockedError as e:
                query_run.success = False
                query_run.error = f"{type(e).__name__}: {e}"
                logger.warning(
                    "Query %s blacklisted on exit IP %s (attempt %d/%d)",
                    query, query_run.exit_ip or "unknown", attempt, MAX_BLACKLIST_RETRIES,
                )
            except Exception as e:
                query_run.success = False
                query_run.error = f"{type(e).__name__}: {e}"
                logger.exception("Query %s failed", query)
                return None
            finally:
                query_run.run_end = datetime.now(timezone.utc)
                query_run.save()

            # Only the MarketplaceBlockedError path falls through to here.
            if attempt >= MAX_BLACKLIST_RETRIES:
                break
            if not self.change_ip():
                self.log(
                    f"Could not rotate away from {query_run.exit_ip or 'the current IP'}, "
                    f"abandoning {query} this pass",
                    level=logging.WARNING,
                )
                return None
            # `run_new_query` flips `query.new_query` in memory before it can raise, and
            # the failed attempt never reached `query.save()`. Without re-reading, the
            # retry sees new_query=False and silently takes the run_existing_query
            # branch: the backfill loses both `ignore_first_run` (deliveries created
            # PENDING, so the whole backlog goes to Discord) and the
            # NEW_PRODUCT_LOAD_MAX cap (that branch has no counter, and general-search
            # pagination is unbounded). A later successful attempt then persists
            # new_query=False, destroying the state for good.
            query.refresh_from_db()

        self.log(
            f"Query {query} still blacklisted after {MAX_BLACKLIST_RETRIES} attempts, "
            f"skipping it this pass",
            level=logging.WARNING,
        )
        return None

    def _current_exit_ip(self) -> str:
        """Best-effort egress IP, recorded on QueryRun for failure attribution.

        Sampled per attempt rather than per pass on purpose: Tor rebuilds circuits on its
        own schedule, and "did the exit change mid-pass?" is exactly the question this
        column exists to answer (IP reputation vs. a sliding-window rate limit). The
        lookup does not touch the marketplace, so it costs nothing against the budget there.

        Never fatal: an unreachable IP-echo service must not take down a scraping pass.
        """
        try:
            return str(ip_address(self.ip_changer.get_current_ip()))
        except Exception:
            logger.warning("Could not determine the current exit IP", exc_info=True)
            return ""

    def _sleep_between_queries(self) -> None:
        wait = uniform(*QUERY_WAIT_TIME)
        logger.debug("Sleeping %.1f s before the next query", wait)
        sleep(wait)

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

    def change_ip(self) -> bool:
        """Rotate to a different egress IP. Returns whether the exit actually changed.

        Does NOT validate the new IP against the marketplace — validation is the caller's next real
        query attempt (see `_run_query_with_rotation`). This used to call
        `renew_ip_bazos_ok`, which validated each candidate with the same misleading
        fixed-URL probe, so it could burn every attempt rejecting usable IPs or settle on
        one the probe liked and the query did not.

        The return value matters because `renew_ip_and_check_new` gives up after a bounded
        number of NEWNYM attempts and hands back the *old* IP. Retrying a query against the
        exit that just 403'd it cannot succeed, so the caller stops instead.

        Only the outcome goes to Discord (`self.log`); the "current=" line is local. During
        the clustered-403 runs this whole change targets, `change_ip` fires up to twice per
        query across every query in the pass, and a webhook that rate-limits around 30
        posts/min is easy to swamp.
        """
        old_ip = self._current_exit_ip()
        logger.info("Changing IP, current=%s", old_ip or "unknown")
        new_ip = self.ip_changer.renew_ip_and_check_new()
        # An unknown old IP is treated as a successful rotation: the caller should spend
        # its remaining attempts rather than give up on a guess.
        rotated = new_ip != old_ip
        if rotated:
            self.log(f"NEW IP={new_ip}")
        else:
            self.log(f"IP rotation FAILED, still on {new_ip}", level=logging.WARNING)
        return rotated

