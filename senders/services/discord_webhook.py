"""Posting embeds to a Discord webhook.

Separate from `DiscordSender` on purpose. That class is built on `discord_notify`, which
sends `{"content": str}` over `urllib` and expresses its whole retry contract in
`urllib.error` — and it is on the critical per-ad notification path. Embeds need
`requests` and a different exception family; putting both transports behind one `_send`
would mean the digest could regress the thing that actually matters.

What the two *do* share is the rate-limit vocabulary: this raises the same
`RateLimitError` with the same `retry_after` semantics, so a caller that already knows how
to back off keeps working.

**Not routed through Tor.** `ip_changer.tor` sets proxies per `Session` and nothing sets
`HTTP_PROXY`, so a bare `requests.post` goes out clear — which is required here, because
Discord blocks Tor exits. Do not "helpfully" hand this a Tor session.
"""
import json
import logging
from random import uniform
from time import sleep

import requests

from senders.exceptions import RateLimitError

logger = logging.getLogger(__name__)

#: Discord's documented structural limits. Exceeding one is a 400 with a body nobody
#: reads, so the payload is checked here instead.
MAX_EMBEDS_PER_MESSAGE = 10
MAX_EMBED_CHARS_TOTAL = 6000
MAX_TITLE_CHARS = 256
MAX_DESCRIPTION_CHARS = 4096
MAX_FIELDS = 25
MAX_FIELD_NAME_CHARS = 256
MAX_FIELD_VALUE_CHARS = 1024
MAX_FOOTER_CHARS = 2048

#: Matches DiscordSender: same budget, same backoff.
MAX_CONNECTION_RETRIES = 5

#: Longest wait we will believe. Discord's webhook limits resolve in seconds; far more
#: than this means something unusual, and blocking on it is worse than failing.
MAX_RETRY_AFTER_SECONDS = 300

REQUEST_TIMEOUT = (10, 10)


def retry_after_seconds(raw):
    """Parse a `Retry-After` value, or None when it is absent or not believable.

    Shared with `DiscordSender._retry_after` so the two transports cannot disagree about
    what counts as a usable wait. None is the safe direction: the caller treats it as an
    ordinary failure and spends its retry budget.
    """
    try:
        seconds = float(raw)
    except (TypeError, ValueError):
        return None
    if seconds <= 0 or seconds > MAX_RETRY_AFTER_SECONDS:
        return None
    return seconds


def embed_chars(embeds):
    """Discord counts title + description + field names/values + footer, across all embeds."""
    total = 0
    for embed in embeds:
        total += len(embed.get("title", "")) + len(embed.get("description", ""))
        total += len(embed.get("footer", {}).get("text", ""))
        for field in embed.get("fields", []):
            total += len(field.get("name", "")) + len(field.get("value", ""))
    return total


def check_payload(embeds):
    """Raise before opening a socket rather than after Discord refuses.

    A 400 from a malformed payload is a bug in the renderer, and finding out from an HTTP
    status makes it look like a network problem.
    """
    if len(embeds) > MAX_EMBEDS_PER_MESSAGE:
        raise ValueError(f"{len(embeds)} embeds, Discord allows {MAX_EMBEDS_PER_MESSAGE}")
    total = embed_chars(embeds)
    if total > MAX_EMBED_CHARS_TOTAL:
        raise ValueError(f"{total} embed characters, Discord allows {MAX_EMBED_CHARS_TOTAL}")


def post_embeds(url, embeds, *, content=None, timeout=REQUEST_TIMEOUT):
    """POST an embeds payload, with DiscordSender's retry semantics over `requests`.

    * 429 → `RateLimitError` carrying the wait, so the caller can pause rather than fail.
    * connection error / timeout / 5xx → retried `MAX_CONNECTION_RETRIES` times, then raised.
    * any other 4xx → raised immediately. A malformed payload does not become valid by
      being sent five times, and retrying it hides the bug behind a delay.
    """
    check_payload(embeds)
    payload = {"embeds": embeds}
    if content:
        payload["content"] = content

    attempts = 0
    while True:
        try:
            response = requests.post(url, json=payload, timeout=timeout)
        except (requests.ConnectionError, requests.Timeout):
            attempts += 1
            logger.warning("Discord webhook unreachable (%d/%d)", attempts, MAX_CONNECTION_RETRIES)
            if attempts >= MAX_CONNECTION_RETRIES:
                raise
            sleep(uniform(2, 8))
            continue

        if response.status_code == 429:
            wait = response.headers.get("Retry-After")
            if wait is None:
                try:
                    wait = json.loads(response.text or "{}").get("retry_after")
                except ValueError:
                    wait = None
            raise RateLimitError(retry_after=retry_after_seconds(wait))

        if 500 <= response.status_code < 600:
            attempts += 1
            logger.warning(
                "Discord webhook returned %d (%d/%d)",
                response.status_code, attempts, MAX_CONNECTION_RETRIES,
            )
            if attempts >= MAX_CONNECTION_RETRIES:
                response.raise_for_status()
            sleep(uniform(2, 8))
            continue

        response.raise_for_status()
        return
