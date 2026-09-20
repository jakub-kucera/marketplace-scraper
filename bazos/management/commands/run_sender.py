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
from time import monotonic, sleep

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.timezone import now

from bazos.const import MAX_SEND_ATTEMPTS, SENDER_BATCH_SIZE, SENDER_POLL_INTERVAL
from bazos.models import AdDelivery, AdStatus
from senders.exceptions import RateLimitError
from senders.models import Discord
from senders.services.discord_sender import DiscordSender

logger = logging.getLogger(__name__)


def _announce_failures(failures: list) -> None:
    """Say out loud that a notification was permanently lost.

    A FAILED delivery is the product's one job not happening, and until this it happened
    silently — 65 of them accumulated over six weeks and were noticed only because a
    dashboard put the count on a card. Routed to the `for_logging` channels, the same
    place the zero-rows canary goes, because that is where "something is wrong" already
    lives.

    Never raises: this runs after the status writes have been committed, and a webhook
    that is itself refusing us must not turn a recorded failure into an unrecorded one.
    """
    if not failures:
        return
    lines = [f"⚠️ {len(failures)} notification(s) permanently failed:"]
    lines += [
        f"• delivery {d.pk} — {d.ad.name[:70]} (query: {d.query.text or d.query.marketplace})"
        for d in failures[:10]
    ]
    if len(failures) > 10:
        lines.append(f"• …and {len(failures) - 10} more")
    lines.append("Requeue them from the Ad deliveries changelist once the cause is fixed.")
    message = "\n".join(lines)

    for channel in Discord.objects.filter(for_logging=True):
        try:
            DiscordSender.from_model(channel).send_plain(message)
        except Exception:
            logger.exception("Could not announce delivery failures to %s", channel.channel_name)


class Command(BaseCommand):
    help = "Polls APPROVED deliveries and delivers them to Discord"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        #: Discord webhook id -> monotonic deadline before which it will refuse us.
        #: Process-local on purpose: a cooldown resolves in seconds, so persisting it
        #: would cost a migration and a write per rate limit to save, at worst, one
        #: wasted 429 after a restart.
        self._cooling: dict[int, float] = {}

    def _cooling_senders(self) -> list[int]:
        """Webhook ids still inside a Retry-After window, pruning the expired ones."""
        now = monotonic()
        self._cooling = {pk: until for pk, until in self._cooling.items() if until > now}
        return list(self._cooling)

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
            # Rate limits are **per webhook**, so a channel that is cooling must be
            # excluded from the *query*, not skipped in Python. The batch is the oldest
            # `SENDER_BATCH_SIZE` by `created`: a burst of 50 ads for one channel would
            # otherwise fill the whole batch with rows that get skipped, and every other
            # channel would wait behind them for no reason. Excluded here, the batch
            # fills with work that can actually be done, and the cooling channel keeps
            # its place in the queue.
            deliveries = list(
                AdDelivery.objects
                .select_for_update(skip_locked=True, of=("self",))
                .filter(status=AdStatus.APPROVED)
                .exclude(query__sender_id__in=self._cooling_senders())
                .select_related("ad", "query__sender")
                .order_by("created")[:SENDER_BATCH_SIZE]
            )
            failures: list[AdDelivery] = []
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
                    failures.append(delivery)
                else:
                    try:
                        sender = DiscordSender.from_model(config)
                        sender.send_sendable([delivery.ad])
                        delivery.status = AdStatus.SENT
                        delivery.sent_at = now()
                        logger.info("Sent delivery %d (ad %d)", delivery.pk, delivery.ad_id)
                    except RateLimitError as exc:
                        if exc.retry_after is not None:
                            # Backpressure, not failure. Discord said how long to wait, so
                            # waiting is the correct response and spending a *failure*
                            # budget on it is not: the budget exists for errors we cannot
                            # interpret, and charging flow control to it is what marked 65
                            # deliveries permanently FAILED inside two seconds apiece.
                            self._cooling[config.pk] = monotonic() + exc.retry_after
                            logger.warning(
                                "Delivery %d: %s rate-limited, pausing that channel for %.1fs",
                                delivery.pk, config.channel_name, exc.retry_after,
                            )
                            continue          # left APPROVED, keeps its place in the queue
                        delivery.send_attempts += 1
                        if delivery.send_attempts >= MAX_SEND_ATTEMPTS:
                            delivery.status = AdStatus.FAILED
                            logger.error(
                                "Delivery %d permanently FAILED after %d attempts",
                                delivery.pk, delivery.send_attempts,
                            )
                            failures.append(delivery)
                        else:
                            logger.warning(
                                "Delivery %d refused with no Retry-After (attempt %d/%d), will retry",
                                delivery.pk, delivery.send_attempts, MAX_SEND_ATTEMPTS,
                            )
                delivery.save(update_fields=["status", "sent_at", "send_attempts"])

        # Outside the transaction: announcing a failure must not hold locks, and a webhook
        # that is itself refusing us must not roll back the status write that records it.
        _announce_failures(failures)
        return len(deliveries)

    def handle(self, *args, **options):
        logger.info("run_sender started")
        while True:
            processed = self.run_once()
            if options.get("once"):
                return
            if processed == 0:
                sleep(SENDER_POLL_INTERVAL)
