"""Management command: compare_bazos_scrapers

One-off validation tool: runs BazosScraper (HTML) and BazosApiScraper (hidden
API) against the same Query rows and reports how their discovered ad ids
overlap. Read-only — never writes to the DB, never touches Ad.status. Not part
of the production pipeline: run_scraper only ever dispatches by
query.marketplace, and no Query currently has marketplace="bazos_api".

Usage:
    python manage.py compare_bazos_scrapers                 # first 5 enabled queries
    python manage.py compare_bazos_scrapers --query-id 12
    python manage.py compare_bazos_scrapers --limit 20
"""
import logging

import requests
from django.core.management.base import BaseCommand

from bazos.models import Query
from bazos.scraping.bazos.bazos_api_scraper import BazosApiScraper
from bazos.scraping.bazos.bazos_scraper import BazosScraper
from ip_changer.tor import PROXIES

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Compares BazosScraper (HTML) vs BazosApiScraper (hidden API) on the same queries. Read-only."

    def add_arguments(self, parser):
        parser.add_argument("--query-id", type=int, help="Compare only this Query id")
        parser.add_argument("--limit", type=int, default=5, help="How many enabled queries to compare (default 5)")

    def handle(self, *args, **options):
        session = requests.Session()
        session.proxies = PROXIES

        html_scraper = BazosScraper(session)
        api_scraper = BazosApiScraper(session)

        if options["query_id"]:
            queries = Query.objects.filter(pk=options["query_id"])
        else:
            queries = Query.objects.filter(enabled=True)[: options["limit"]]

        for query in queries:
            self.stdout.write(f"--- Query {query.pk}: {query} ---")

            # BazosScraper.extract_product leaves external_id as the raw string
            # parsed from the URL path; BazosApiScraper's is already an int.
            # Normalise both to int before comparing.
            html_ids = {int(ad.external_id) for ad in html_scraper.run_query(query)}
            api_ids = {int(ad.external_id) for ad in api_scraper.run_query(query)}

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
