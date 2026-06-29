"""Tests for DiscordSender._send retry/backoff behaviour (no DB needed)."""
from unittest.mock import MagicMock, patch, call
from urllib.error import HTTPError, URLError

import pytest

import senders.services.discord_sender as ds_module
from senders.exceptions import RateLimitError
from senders.services.discord_sender import DiscordSender, MAX_CONNECTION_RETRIES


@pytest.fixture()
def sender():
    """DiscordSender with a mocked notifier and sleep patched to a no-op."""
    s = DiscordSender.__new__(DiscordSender)
    s.notify = False
    s.notifier = MagicMock()
    s.preview_link = False
    return s


# ---------------------------------------------------------------------------
# _send — success path
# ---------------------------------------------------------------------------

def test_send_calls_notifier_once_on_success(sender):
    with patch("senders.services.discord_sender.sleep"):
        sender._send("hello")
    sender.notifier.send.assert_called_once_with("hello", print_message=False)


# ---------------------------------------------------------------------------
# _send — rate-limit (HTTPError) → RateLimitError
# ---------------------------------------------------------------------------

def test_send_raises_rate_limit_error_on_http_error(sender):
    """HTTPError from Discord is immediately converted to RateLimitError."""
    sender.notifier.send.side_effect = HTTPError(None, 429, "Too Many Requests", {}, None)
    with patch("senders.services.discord_sender.sleep"):
        with pytest.raises(RateLimitError):
            sender._send("msg")


def test_send_http_error_does_not_retry(sender):
    """DiscordSender must not loop internally on rate limits — run_sender does that."""
    sender.notifier.send.side_effect = HTTPError(None, 429, "Too Many Requests", {}, None)
    with patch("senders.services.discord_sender.sleep"):
        with pytest.raises(RateLimitError):
            sender._send("msg")
    assert sender.notifier.send.call_count == 1


# ---------------------------------------------------------------------------
# _send — URLError capped retry
# ---------------------------------------------------------------------------

def test_send_raises_after_max_connection_retries(sender):
    sender.notifier.send.side_effect = URLError("network down")
    with patch("senders.services.discord_sender.sleep"):
        with pytest.raises(URLError):
            sender._send("msg")
    assert sender.notifier.send.call_count == MAX_CONNECTION_RETRIES


def test_send_connection_error_count_resets_per_call(sender):
    """Two separate _send calls: first exhausts retries, second also exhausts
    independently — the counter must NOT carry over."""
    sender.notifier.send.side_effect = URLError("down")
    with patch("senders.services.discord_sender.sleep"):
        with pytest.raises(URLError):
            sender._send("first")
        with pytest.raises(URLError):
            sender._send("second")
    assert sender.notifier.send.call_count == MAX_CONNECTION_RETRIES * 2


def test_send_sleeps_between_connection_retries(sender):
    sender.notifier.send.side_effect = URLError("down")
    sleep_mock = MagicMock()
    with patch("senders.services.discord_sender.sleep", sleep_mock):
        with pytest.raises(URLError):
            sender._send("msg")
    # sleep should be called for each retry *before* the cap (MAX-1 times for
    # connection errors) plus the success sleep is never reached.
    connection_sleeps = MAX_CONNECTION_RETRIES - 1
    assert sleep_mock.call_count == connection_sleeps


# ---------------------------------------------------------------------------
# _send — URLError then success (recovers before cap)
# ---------------------------------------------------------------------------

def test_send_recovers_after_transient_connection_error(sender):
    sender.notifier.send.side_effect = [URLError("timeout"), None]
    with patch("senders.services.discord_sender.sleep"):
        sender._send("msg")  # must not raise
    assert sender.notifier.send.call_count == 2


# ---------------------------------------------------------------------------
# MAX_CONNECTION_RETRIES constant is importable and sensible
# ---------------------------------------------------------------------------

def test_max_connection_retries_is_positive_int():
    assert isinstance(MAX_CONNECTION_RETRIES, int)
    assert MAX_CONNECTION_RETRIES > 0
