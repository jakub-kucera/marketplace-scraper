"""The exit IP a block response names, and why that is the only one worth recording.

`QueryRun.exit_ip` used to be filled from an icanhazip lookup taken just before each
attempt. The Tor proxy runs `SocksPort ... IsolateDestAddr`, so that lookup travels a
different circuit than the marketplace request and reports a different exit node —
measured live 2026-08-29: one session, `icanhazip.com` -> 171.25.193.38, `pc.bazos.cz` ->
37.114.63.5, `nabytek.bazos.cz` -> 193.189.100.201. The column was noise, which is why
five days of it showed 305 of 331 IPs both succeeding and failing.

The block response names the real one, in both body formats Bazos serves.
"""
from unittest.mock import MagicMock

import pytest

from bazos.exceptions import MarketplaceBlockedError, parse_blocked_exit_ip

HTML_BODY = (
    "<H1>Forbidden</H1>You don't have permission to access this server. IP: 37.114.63.5"
)
JSON_BODY = (
    '{"error_code":"403","message":"You don\'t have permission to access this server. '
    'IP: 86.54.28.49"}'
)


@pytest.mark.parametrize("body,expected", [
    (HTML_BODY, "37.114.63.5"),
    (JSON_BODY, "86.54.28.49"),
    ("<H1>Forbidden</H1>You don't have permission. IP: 2001:db8::1", "2001:db8::1"),
])
def test_parses_the_ip_out_of_both_body_formats(body, expected):
    assert parse_blocked_exit_ip(body) == expected


@pytest.mark.parametrize("body", [
    "",
    "<H1>Forbidden</H1>",
    "IP: not.an.address",
    "IP: 999.999.999.999",
])
def test_returns_empty_rather_than_junk(body):
    """`exit_ip` is a 45-char indexed column whose whole purpose is being grouped on —
    an unparseable value is worse there than no value."""
    assert parse_blocked_exit_ip(body) == ""


def test_only_the_head_of_the_body_is_scanned():
    """A 403 that served a whole page must not cost a scan of it, and an `IP:` buried
    deep in one is prose, not the nginx deny body."""
    assert parse_blocked_exit_ip("x" * 5000 + "IP: 1.2.3.4") == ""


def test_from_response_carries_the_ip_but_leaves_the_message_alone():
    """`QueryRun.error` stores `f"{type(e).__name__}: {e}"`. Putting the IP in the message
    would split one failure mode into a few hundred one-row groups; the indexed column is
    where it belongs.
    """
    error = MarketplaceBlockedError.from_response(MagicMock(text=HTML_BODY))

    assert error.exit_ip == "37.114.63.5"
    assert str(error) == "Marketplace returned 403/429 for the current IP"
