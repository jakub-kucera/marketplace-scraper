"""Exceptions raised by sender services."""


class RateLimitError(Exception):
    """Raised by DiscordSender when Discord returns HTTP 429 (rate limit).

    The sender process owns the retry policy across polls — DiscordSender
    raises this to signal the failure type without looping internally.
    """
    pass
