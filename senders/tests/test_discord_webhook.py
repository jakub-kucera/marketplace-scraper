"""Tests for the embeds transport (`senders/services/discord_webhook.py`).

The retry policy is the whole content of this module, and each branch is a decision that
costs something when it is wrong: retrying a 400 hides a renderer bug behind a delay,
retrying a 429 makes a rate limit worse, and not retrying a 502 loses a digest to one bad
second.
"""
from unittest.mock import Mock, patch

import pytest
import requests

from senders.exceptions import RateLimitError
from senders.services.discord_webhook import (
    MAX_CONNECTION_RETRIES,
    MAX_RETRY_AFTER_SECONDS,
    check_payload,
    embed_chars,
    post_embeds,
    retry_after_seconds,
)

URL = "https://discord.test/webhook"
EMBEDS = [{"title": "Daily digest", "description": "x"}]


def _response(status, headers=None, text=""):
    response = Mock(spec=requests.Response)
    response.status_code = status
    response.headers = headers or {}
    response.text = text
    response.raise_for_status = Mock(
        side_effect=requests.HTTPError(f"{status}") if status >= 400 else None
    )
    return response


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.5", 1.5),
        (2, 2.0),
        (None, None),
        ("", None),
        ("soon", None),
        ("0", None),
        (str(MAX_RETRY_AFTER_SECONDS + 1), None),
    ],
)
def test_retry_after_is_believed_only_when_it_is_believable(raw, expected):
    """None is the safe direction — the caller spends its retry budget instead of
    sleeping on a number a proxy made up."""
    assert retry_after_seconds(raw) == expected


def test_embed_characters_count_every_field_discord_counts():
    embeds = [{
        "title": "ab", "description": "cde",
        "footer": {"text": "fg"},
        "fields": [{"name": "h", "value": "ij"}],
    }]

    assert embed_chars(embeds) == 10


def test_an_oversized_payload_is_refused_before_a_socket_is_opened():
    """A 400 for a malformed payload is a renderer bug, and finding out from an HTTP
    status makes it look like a network problem."""
    with pytest.raises(ValueError, match="embed characters"):
        check_payload([{"description": "x" * 7000}])

    with pytest.raises(ValueError, match="embeds"):
        check_payload([{"title": "x"}] * 11)


def test_a_rate_limit_becomes_a_rate_limit_error_carrying_the_wait():
    with patch("requests.post", return_value=_response(429, {"Retry-After": "3"})):
        with pytest.raises(RateLimitError) as excinfo:
            post_embeds(URL, EMBEDS)

    assert excinfo.value.retry_after == 3.0


def test_the_wait_is_read_from_the_body_when_the_header_is_missing():
    """Discord sends `retry_after` in JSON on the webhook endpoints, header or not."""
    body = _response(429, {}, text='{"retry_after": 2.5}')
    with patch("requests.post", return_value=body):
        with pytest.raises(RateLimitError) as excinfo:
            post_embeds(URL, EMBEDS)

    assert excinfo.value.retry_after == 2.5


def test_a_server_error_is_retried_then_raised():
    post = Mock(return_value=_response(503))
    with patch("requests.post", post), patch("senders.services.discord_webhook.sleep"):
        with pytest.raises(requests.HTTPError):
            post_embeds(URL, EMBEDS)

    assert post.call_count == MAX_CONNECTION_RETRIES


def test_a_client_error_is_raised_immediately():
    """Five identical 400s are five ways to learn the same thing, slowly."""
    post = Mock(return_value=_response(400))
    with patch("requests.post", post), patch("senders.services.discord_webhook.sleep"):
        with pytest.raises(requests.HTTPError):
            post_embeds(URL, EMBEDS)

    assert post.call_count == 1


def test_a_transport_failure_is_retried_and_then_succeeds():
    post = Mock(side_effect=[requests.ConnectionError("down"), _response(204)])
    with patch("requests.post", post), patch("senders.services.discord_webhook.sleep"):
        post_embeds(URL, EMBEDS)

    assert post.call_count == 2


def test_content_is_only_sent_when_there_is_some():
    post = Mock(return_value=_response(204))
    with patch("requests.post", post):
        post_embeds(URL, EMBEDS)

    assert post.call_args.kwargs["json"] == {"embeds": EMBEDS}
