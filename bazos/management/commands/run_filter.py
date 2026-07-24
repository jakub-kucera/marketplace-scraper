"""Management command: run_filter

Polls ads with status PENDING or PRICE_CHANGED and applies the filter rule
engine. Approved ads become APPROVED (ready for run_sender). Rejected ads
become REJECTED and are recorded with a reason.

Usage:
    python manage.py run_filter
"""
import logging
from time import sleep

from django.core.management.base import BaseCommand
from django.db import transaction

from bazos.const import FILTER_BATCH_SIZE, FILTER_POLL_INTERVAL
from bazos.filters import (
    BlocklistKeywordRule,
    FilterResult,
    PriceDropRule,
    PriceRangeRule,
    PublisherBlocklistRule,
    RequiredKeywordRule,
    RuleEngine,
)
from bazos.models import Ad, AdStatus

logger = logging.getLogger(__name__)

rule_engine = RuleEngine(rules=[
    PriceRangeRule(),
    BlocklistKeywordRule(),
    RequiredKeywordRule(),
    PublisherBlocklistRule(),
    PriceDropRule(),
])


class Command(BaseCommand):
    help = "Polls PENDING/PRICE_CHANGED ads and applies filter rules"

    def handle(self, *args, **options):
        logger.info("run_filter started")
        while True:
            with transaction.atomic():
                ads = list(
                    Ad.objects
                    .select_for_update(skip_locked=True)
                    .filter(status__in=[AdStatus.PENDING, AdStatus.PRICE_CHANGED])
                    .select_related("query", "email_publisher", "phone_publisher")
                    .order_by("created")[:FILTER_BATCH_SIZE]
                )
                for ad in ads:
                    result, reason = rule_engine.apply(ad)
                    if result != FilterResult.REJECT:
                        ad.status = AdStatus.APPROVED
                    else:
                        ad.status = AdStatus.REJECTED
                    ad.filter_reason = reason
                    ad.save(update_fields=["status", "filter_reason"])
                    logger.info(
                        "Filtered ad %d → %s%s",
                        ad.pk, ad.status,
                        f" ({reason})" if reason else "",
                    )

            if not ads:
                sleep(FILTER_POLL_INTERVAL)
