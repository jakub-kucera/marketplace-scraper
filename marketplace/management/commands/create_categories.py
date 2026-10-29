import logging
from time import sleep

from django.core.management.base import BaseCommand
import requests

from marketplace.const import BAZOS_API_BASE_URL
from marketplace.models import Section, Category
from marketplace.scraping.bazos.user_agent import default_user_agent

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync Bazos categories from the live api/v1/categories.php endpoint"

    def handle(self, *args, **options):
        headers = {"User-Agent": default_user_agent()}
        created_count = 0
        updated_count = 0

        for section in Section.objects.all():
            response = requests.get(
                f"{BAZOS_API_BASE_URL}/categories.php",
                params={"section": section.bazos_id},
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            categories = response.json()

            seen_bazos_ids = set()
            for category in categories:
                bazos_id = int(category["id"])
                seen_bazos_ids.add(bazos_id)
                _, created = Category.objects.update_or_create(
                    bazos_id=bazos_id,
                    defaults={"name": category["title"], "url": category["url"], "section": section},
                )
                created_count += created
                updated_count += not created

            stale_bazos_ids = set(
                Category.objects.filter(section=section).values_list("bazos_id", flat=True)
            ) - seen_bazos_ids
            if stale_bazos_ids:
                logger.warning(
                    "Categories in DB for section %s but not returned by the API (left untouched): %s",
                    section.name,
                    sorted(stale_bazos_ids),
                )

            sleep(5)

        logger.info("Categories synced: %d created, %d updated", created_count, updated_count)
