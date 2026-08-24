"""Tests for DiscordSender — `_send` retry/backoff and `_format_product_message`."""
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

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


# ---------------------------------------------------------------------------
# _format_product_message — the marketplace link plus the optional admin link
# ---------------------------------------------------------------------------

class _Sendable:
    """Minimal Sendable. `admin_url` is set per-test to model both shapes."""

    def __init__(self, message="Ad 1\n1000 Kc", link="https://pc.bazos.cz/inzerat/1/x.php"):
        self.message = message
        self.link = link


def test_format_product_message_appends_the_admin_link(sender):
    s = _Sendable()
    s.admin_url = "http://raspberrypi5.local:8000/admin/bazos/ad/14084/change/"

    message = sender._format_product_message(s)

    assert s.link in message
    assert message.endswith("\nadmin: <http://raspberrypi5.local:8000/admin/bazos/ad/14084/change/>")


def test_format_product_message_omits_the_admin_link_when_absent(sender):
    """`admin_url` is not a Sendable protocol member — a sendable without one must format."""
    message = sender._format_product_message(_Sendable())

    assert "admin:" not in message
    assert message.endswith("<https://pc.bazos.cz/inzerat/1/x.php>")


def test_admin_link_stays_suppressed_when_preview_link_is_on(sender):
    """`preview_link` unwraps the *marketplace* link; the admin host is unreachable by
    Discord's crawler, so its link is wrapped either way."""
    sender.preview_link = True
    s = _Sendable()
    s.admin_url = "http://raspberrypi5.local:8000/admin/bazos/ad/14084/change/"

    message = sender._format_product_message(s)

    assert f"\nadmin: <{s.admin_url}>" in message
    assert f"<{s.link}>" not in message  # marketplace link unwrapped, admin link not


def test_format_product_message_notify_prefix_still_leads(sender):
    sender.notify = True
    s = _Sendable()
    s.admin_url = "http://localhost:8000/admin/bazos/ad/1/change/"

    assert sender._format_product_message(s).startswith("@here \n")
