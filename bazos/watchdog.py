"""Which pipeline stage has stopped moving. Run from the job cluster, not from the stages.

Every other alarm here lives inside the process it watches: the canaries in `ScrapeRunner`,
the failure announcement in `run_sender`. On 2026-10-16 scraper, filter and sender all
crashlooped for 22 hours, so none of them could say anything, while qcluster stayed up and
kept the heartbeat green. This looks at the stages from outside, through the rows they
should be writing.
"""
from datetime import datetime

from django.db.models import Max, Min
from django.utils import timezone

from bazos.const import WATCHDOG_FILTER_SILENCE, WATCHDOG_SCRAPER_SILENCE, WATCHDOG_SENDER_SILENCE
from bazos.models import AdDelivery, AdStatus, Query, QueryRun


def _ago(now: datetime, then: datetime | None) -> str:
    if then is None:
        return "ever"
    return f"{(now - then).total_seconds() / 3600:.1f} h"


def find_stalls(now: datetime | None = None) -> list[str]:
    """One line per stalled stage; empty when healthy. Thresholds are in `bazos.const`."""
    now = now or timezone.now()
    stalls = []

    if Query.objects.filter(enabled=True).exists():
        last_ok = QueryRun.objects.filter(success=True).aggregate(t=Max("run_start"))["t"]
        if last_ok is None or now - last_ok > WATCHDOG_SCRAPER_SILENCE:
            stalls.append(f"scraper: no query has succeeded for {_ago(now, last_ok)}")

    oldest_pending = AdDelivery.objects.filter(status=AdStatus.PENDING).aggregate(t=Min("created"))["t"]
    if oldest_pending is not None and now - oldest_pending > WATCHDOG_FILTER_SILENCE:
        stalls.append(f"filter: a PENDING delivery has waited {_ago(now, oldest_pending)}")

    # Keyed on the last send rather than on how long a row has waited: an APPROVED row
    # behind a Discord rate limit can wait a while, but the sender is still sending.
    if AdDelivery.objects.filter(status=AdStatus.APPROVED).exists():
        last_sent = AdDelivery.objects.aggregate(t=Max("sent_at"))["t"]
        if last_sent is None or now - last_sent > WATCHDOG_SENDER_SILENCE:
            stalls.append(f"sender: deliveries are waiting and nothing was sent for {_ago(now, last_sent)}")

    return stalls
