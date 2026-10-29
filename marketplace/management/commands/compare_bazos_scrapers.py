"""Management command: compare_bazos_scrapers

One-off validation tool: runs BazosScraper (HTML) and BazosApiScraper (hidden
API) against the same Query rows and reports how their discovered ad ids
overlap. Read-only — never writes to the DB, never touches Ad.status. Not part
of the production pipeline: run_scraper only ever dispatches by
query.marketplace, and no Query currently has marketplace="bazos_api".

Usage:
    python manage.py compare_bazos_scrapers                 # first 5 enabled Bazos queries
    python manage.py compare_bazos_scrapers --query-id 12
    python manage.py compare_bazos_scrapers --limit 20
"""
import logging
from itertools import islice

from django.core.management.base import BaseCommand

from marketplace.const import COMPARE_MAX_ADS
from marketplace.models import Marketplace, Query
from marketplace.scraping.bazos.bazos_api_scraper import BazosApiScraper
from marketplace.scraping.bazos.bazos_scraper import BazosScraper
from marketplace.scraping.session import AllCircuitsBlocked, build_ip_changer, with_rotation

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Compares BazosScraper (HTML) vs BazosApiScraper (hidden API) on the same queries. Read-only."

    def add_arguments(self, parser):
        parser.add_argument("--query-id", type=int, help="Compare only this Query id")
        parser.add_argument("--limit", type=int, default=5, help="How many enabled queries to compare (default 5)")

    def handle(self, *args, **options):
        changer = build_ip_changer()
        assert changer.session is not None
        html_scraper = BazosScraper(changer.session)
        api_scraper = BazosApiScraper(changer.session)

        if options["query_id"]:
            queries = Query.objects.filter(pk=options["query_id"])
        else:
            # Ordered, because an unordered slice is whichever rows Postgres returns first,
            # and filtered, because a Vinted or Sbazar query fed to these scrapers compares nothing.
            queries = Query.objects.filter(
                enabled=True, marketplace__in=(Marketplace.BAZOS, Marketplace.BAZOS_API)
            ).order_by("pk")[: options["limit"]]

        for query in queries:
            # Logged, not just written to stdout: stdout is a StringIO the job wrapper only
            # reads after this command returns, so a task that times out mid-query (see
            # bazos_scraper.run_query's page cap notes) would otherwise leave no record of
            # which query it died on.
            logger.info("compare_bazos_scrapers: starting query %s: %s", query.pk, query)
            self.stdout.write(f"--- Query {query.pk}: {query} ---")

            # Rotation matters more here than anywhere else, because of what this output is
            # read as. A 403'd circuit returns nothing, and "nothing" from one of the two
            # scrapers is indistinguishable from the parser drift this command exists to
            # detect — a canary that cannot tell "blocked" from "broken" is worse than none.
            try:
                html_ids, html_floor = self._ids(html_scraper, changer, query, "html")
                api_ids, api_floor = self._ids(api_scraper, changer, query, "api")
            except AllCircuitsBlocked as e:
                self.stdout.write(self.style.WARNING(f"  blocked, no comparison made: {e}"))
                continue

            # Both walks stop after the same number of ads, so whichever transport skipped
            # something reaches deeper. Ids below the shallower walk's last ad are the edge
            # of the window, not drift, and are dropped from both sides.
            floor = max(html_floor, api_floor)
            html_ids = {i for i in html_ids if i >= floor}
            api_ids = {i for i in api_ids if i >= floor}
            common = html_ids & api_ids
            only_html = html_ids - api_ids
            only_api = api_ids - html_ids

            self.stdout.write(
                f"html={len(html_ids)} api={len(api_ids)} common={len(common)} "
                f"only_html={len(only_html)} only_api={len(only_api)} "
                f"html_requests={html_scraper.sent_requests_count} api_requests={api_scraper.sent_requests_count}"
            )
            if only_html:
                self.stdout.write(f"  only in html (sample): {sorted(only_html)[:10]}")
            if only_api:
                self.stdout.write(f"  only in api (sample): {sorted(only_api)[:10]}")

    @staticmethod
    def _ids(scraper, changer, query, what: str) -> tuple[set[int], int]:
        """The newest `COMPARE_MAX_ADS` external_ids one scraper finds, and the last of them.

        `BazosScraper.extract_product` leaves `external_id` as the raw string parsed from
        the URL path while `BazosApiScraper`'s is already an int, so both are normalised
        before they are compared. The last id walked is the window's floor; it is the last
        rather than the smallest because a topped ad on page one can be far older.

        The walk is inside the callable on purpose: `run_query` is a generator, so a block
        is raised while it is being *iterated*, not when it is called.
        """
        def fetch(session):
            scraper.session = session
            ids = [int(ad.external_id) for ad in islice(scraper.run_query(query), COMPARE_MAX_ADS)]
            return set(ids), (ids[-1] if ids else 0)

        return with_rotation(changer, fetch, what=f"{what} scrape of query {query.pk}")
