"""Exceptions raised by sender services."""


class RateLimitError(Exception):
    """Raised by DiscordSender when Discord returns HTTP 429 (rate limit).

    The sender process owns the retry policy across polls — DiscordSender raises this to
    signal the failure type without looping internally.

    `retry_after` is the seconds Discord asked us to wait, when it said. That number is
    the difference between a retry budget and a busy-wait: without it `run_sender` retried
    immediately (its poll loop only sleeps when the queue is *empty*), so
    `MAX_SEND_ATTEMPTS` was five attempts inside about a second — every one of them
    against a window that had not reopened. 65 deliveries were marked permanently FAILED
    that way between 2026-08-07 and 2026-09-20.

    `None` means Discord refused without saying how long, which is the case that *should*
    spend the failure budget.
    """

    def __init__(self, message: str = "", retry_after: float | None = None):
        super().__init__(message or "rate limited by Discord")
        self.retry_after = retry_after
