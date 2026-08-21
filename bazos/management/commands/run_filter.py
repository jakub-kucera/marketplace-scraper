"""Management command: run_filter

Polls deliveries with status PENDING or PRICE_CHANGED and applies the filter rule
engine. Approved deliveries become APPROVED (ready for run_sender). Rejected
deliveries become REJECTED and are recorded with a reason.

Usage:
    python manage.py run_filter
"""
import logging
from time import sleep

from django.core.management.base import BaseCommand
from django.db import transaction

from bazos.const import FILTER_BATCH_SIZE, FILTER_POLL_INTERVAL
from bazos.filters import FilterResult, build_rule_engine
from bazos.models import AdDelivery, AdStatus

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Polls PENDING/PRICE_CHANGED deliveries and applies filter rules"

    def handle(self, *args, **options):
        logger.info("run_filter started")
        while True:
            with transaction.atomic():
                deliveries = list(
                    AdDelivery.objects
                    .select_for_update(skip_locked=True, of=("self",))
                    .filter(status__in=[AdStatus.PENDING, AdStatus.PRICE_CHANGED])
                    .select_related("ad", "query", "ad__email_publisher", "ad__phone_publisher")
                    .order_by("created")[:FILTER_BATCH_SIZE]
                )
                for delivery in deliveries:
                    result, reason = build_rule_engine(delivery.query).apply(delivery)
                    if result != FilterResult.REJECT:
                        delivery.status = AdStatus.APPROVED
                    else:
                        delivery.status = AdStatus.REJECTED
                    delivery.filter_reason = reason
                    delivery.save(update_fields=["status", "filter_reason"])
                    logger.info(
                        "Filtered delivery %d (ad %d) → %s%s",
                        delivery.pk, delivery.ad_id, delivery.status,
                        f" ({reason})" if reason else "",
                    )

            if not deliveries:
                sleep(FILTER_POLL_INTERVAL)
