"""Management command: run_sender

Polls deliveries with status APPROVED and delivers them via DiscordSender. On
success the delivery moves to SENT. On a rate-limit error (RateLimitError) the
attempt counter is incremented; after MAX_SEND_ATTEMPTS failures the delivery
is permanently marked FAILED.

Usage:
    python manage.py run_sender
"""
import logging
from time import sleep

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now

from bazos.const import MAX_SEND_ATTEMPTS, SENDER_BATCH_SIZE, SENDER_POLL_INTERVAL
from bazos.models import AdDelivery, AdStatus
from senders.exceptions import RateLimitError
from senders.services.discord_sender import DiscordSender

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Polls APPROVED deliveries and delivers them to Discord"

    def handle(self, *args, **options):
        logger.info("run_sender started")
        while True:
            with transaction.atomic():
                deliveries = list(
                    AdDelivery.objects
                    .select_for_update(skip_locked=True, of=("self",))
                    .filter(status=AdStatus.APPROVED)
                    .select_related("ad", "query__sender")
                    .order_by("created")[:SENDER_BATCH_SIZE]
                )
                for delivery in deliveries:
                    try:
                        sender = DiscordSender.from_model(delivery.query.sender)
                        sender.send_sendable([delivery.ad])
                        delivery.status = AdStatus.SENT
                        delivery.sent_at = now()
                        logger.info("Sent delivery %d (ad %d)", delivery.pk, delivery.ad_id)
                    except RateLimitError:
                        delivery.send_attempts += 1
                        if delivery.send_attempts >= MAX_SEND_ATTEMPTS:
                            delivery.status = AdStatus.FAILED
                            logger.error(
                                "Delivery %d permanently FAILED after %d attempts",
                                delivery.pk, delivery.send_attempts,
                            )
                        else:
                            logger.warning(
                                "Delivery %d rate-limited (attempt %d/%d), will retry",
                                delivery.pk, delivery.send_attempts, MAX_SEND_ATTEMPTS,
                            )
                    delivery.save(update_fields=["status", "sent_at", "send_attempts"])

            if not deliveries:
                sleep(SENDER_POLL_INTERVAL)
