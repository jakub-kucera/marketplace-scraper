import logging

from django.core.management.base import BaseCommand
import requests

from marketplace.const import BAZOS_API_BASE_URL
from marketplace.models import Section
from marketplace.scraping.bazos.user_agent import default_user_agent

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Sync Bazos sections from the live api/v1/sections.php endpoint"

    def handle(self, *args, **options):
        response = requests.get(
            f"{BAZOS_API_BASE_URL}/sections.php",
            headers={"User-Agent": default_user_agent()},
            timeout=10,
        )
        response.raise_for_status()
        sections = response.json()

        seen_bazos_ids = set()
        created_count = 0
        updated_count = 0
        for section in sections:
            bazos_id = section["id"]
            seen_bazos_ids.add(bazos_id)
            _, created = Section.objects.update_or_create(
                bazos_id=bazos_id,
                defaults={"name": section["title"], "url": section["url"]},
            )
            created_count += created
            updated_count += not created

        logger.info("Sections synced: %d created, %d updated", created_count, updated_count)

        stale_bazos_ids = set(Section.objects.values_list("bazos_id", flat=True)) - seen_bazos_ids
        if stale_bazos_ids:
            logger.warning(
                "Sections in DB but not returned by the API (left untouched): %s",
                sorted(stale_bazos_ids),
            )
