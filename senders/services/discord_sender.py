import json
import logging
from time import sleep
from typing import List
from urllib.error import HTTPError, URLError
from random import uniform

import discord_notify as dn

from marketplace.protocols import Sendable
from senders.exceptions import RateLimitError
from senders.services.discord_webhook import retry_after_seconds
from senders.models import Discord
from senders.services.sender import Sender

MAX_CONNECTION_RETRIES = 5

logger = logging.getLogger(__name__)


def _retry_after(error: HTTPError) -> float | None:
    """Seconds Discord asked us to wait, from the header or the JSON body.

    `discord_notify` calls `urlopen`, so the `HTTPError` *is* the response: it carries the
    headers and the body. Both were being discarded, which is why a 429 — flow control
    that says exactly how long to pause — was indistinguishable from a hard failure.

    Returns None when the value is absent, unparseable or implausible; the caller treats
    that as a real failure, which is the safe direction.
    """
    raw = error.headers.get("Retry-After") if error.headers else None
    if raw is None:
        try:
            # Discord also puts it in the body, in seconds, as a float.
            raw = json.loads(error.read() or b"{}").get("retry_after")
        except (ValueError, OSError):
            raw = None
    # Shared with the embeds transport: one definition of "a wait we believe".
    return retry_after_seconds(raw)


class DiscordSender(Sender):

    def __init__(self, url: str, notify: bool = False, preview_link: bool = False):
        super().__init__(notify)
        self.notifier = dn.Notifier(url)
        self.preview_link = preview_link

    @classmethod
    def from_model(cls, sender: Discord):
        return cls(sender.url, sender.notify)

    def _format_link(self, link: str):
        if self.preview_link:
            return link
        else:
            return f"<{link}>"

    def _format_product_message(self, sendable: Sendable) -> str:
        message = "@here \n" if self.notify else ""
        message += self.wrap_multi_line(sendable.message)
        message += self._format_link(sendable.link)
        admin_url = getattr(sendable, "admin_url", None)
        if admin_url:
            message += f"\nadmin: <{admin_url}>"
        return message

    def _send(self, message: str):  # TODO make thread safe
        connection_errors = 0
        while True:
            try:
                self.notifier.send(message, print_message=False)
                sleep(uniform(0.5, 2))
                break
            except HTTPError as e:
                raise RateLimitError(retry_after=_retry_after(e)) from e
            except URLError:
                connection_errors += 1
                logger.warning(
                    "DiscordSender: connection error (%d/%d)",
                    connection_errors, MAX_CONNECTION_RETRIES,
                )
                if connection_errors >= MAX_CONNECTION_RETRIES:
                    raise
                sleep(uniform(2, 8))

    def send_sendable(self, sendables: List[Sendable]):
        for s in sendables:
            self._send(self._format_product_message(s))

    def send_plain(self, text: str):
        if self.notify:
            text = "@here \n" + text
        self._send(text)
