"""Management command: run_sender

Polls ads with status APPROVED and delivers them via DiscordSender. On
success the ad moves to SENT. On a rate-limit error (RateLimitError) the
attempt counter is incremented; after MAX_SEND_ATTEMPTS failures the ad is
permanently marked FAILED.

Usage:
    python manage.py run_sender
"""
import logging
from time import sleep

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now

from bazos.const import MAX_SEND_ATTEMPTS, SENDER_BATCH_SIZE, SENDER_POLL_INTERVAL
from bazos.models import Ad, AdStatus
from senders.exceptions import RateLimitError
from senders.services.discord_sender import DiscordSender

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Polls APPROVED ads and delivers them to Discord"

    def handle(self, *args, **options):
        logger.info("run_sender started")
        while True:
            with transaction.atomic():
                ads = list(
                    Ad.objects
                    .select_for_update(skip_locked=True)
                    .filter(status=AdStatus.APPROVED)
                    .select_related("query__sender")
                    .order_by("created")[:SENDER_BATCH_SIZE]
                )
                for ad in ads:
                    try:
                        sender = DiscordSender.from_model(ad.query.sender)
                        sender.send_sendable([ad])
                        ad.status = AdStatus.SENT
                        ad.sent_at = now()
                        logger.info("Sent ad %d", ad.pk)
                    except RateLimitError:
                        ad.send_attempts += 1
                        if ad.send_attempts >= MAX_SEND_ATTEMPTS:
                            ad.status = AdStatus.FAILED
                            logger.error(
                                "Ad %d permanently FAILED after %d attempts",
                                ad.pk, ad.send_attempts,
                            )
                        else:
                            logger.warning(
                                "Ad %d rate-limited (attempt %d/%d), will retry",
                                ad.pk, ad.send_attempts, MAX_SEND_ATTEMPTS,
                            )
                    ad.save(update_fields=["status", "sent_at", "send_attempts"])

            if not ads:
                sleep(SENDER_POLL_INTERVAL)
