"""Management command: run_sender

Polls deliveries with status APPROVED and delivers them via DiscordSender. On
success the delivery moves to SENT. On a rate-limit error (RateLimitError) the
attempt counter is incremented; after MAX_SEND_ATTEMPTS failures the delivery
is permanently marked FAILED.

Usage:
    python manage.py run_sender           # poll forever (the deployed shape)
    python manage.py run_sender --once    # process one batch and exit
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

    def add_arguments(self, parser):
        parser.add_argument(
            "--once",
            action="store_true",
            help="Process a single batch and exit instead of polling forever.",
        )

    def run_once(self) -> int:
        """Process one batch of deliveries. Returns how many were handled.

        Split out of ``handle`` so the batch is callable without the surrounding
        ``while True`` — see the matching note in run_filter.
        """
        with transaction.atomic():
            deliveries = list(
                AdDelivery.objects
                .select_for_update(skip_locked=True, of=("self",))
                .filter(status=AdStatus.APPROVED)
                .select_related("ad", "query__sender")
                .order_by("created")[:SENDER_BATCH_SIZE]
            )
            for delivery in deliveries:
                # `Query.sender` is SET_NULL, so deleting a Discord row leaves its queries
                # pointing at nothing and their deliveries unsendable. This used to raise
                # AttributeError inside the atomic block: the batch rolled back with the
                # rows still APPROVED, the next poll picked the same ones up, and the
                # daemon crash-looped with every later delivery stuck behind them. FAILED
                # is the terminal state an exhausted retry budget already gets, and it is
                # what lets the queue drain past them.
                config = delivery.query.sender
                if config is None:
                    delivery.status = AdStatus.FAILED
                    logger.error(
                        "Delivery %d permanently FAILED: query %d has no sender configured",
                        delivery.pk, delivery.query_id,
                    )
                else:
                    try:
                        sender = DiscordSender.from_model(config)
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
        return len(deliveries)

    def handle(self, *args, **options):
        logger.info("run_sender started")
        while True:
            processed = self.run_once()
            if options.get("once"):
                return
            if processed == 0:
                sleep(SENDER_POLL_INTERVAL)
