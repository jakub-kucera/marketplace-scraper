import logging
import re
from ipaddress import ip_address

from requests import Response

logger = logging.getLogger(__name__)

#: Both the HTML and the JSON block bodies name the offending IP, in the same shape:
#: `<H1>Forbidden</H1>You don't have permission to access this server. IP: 37.114.63.5`
#: and `{"error_code":"403","message":"You don't have permission to access this server.
#: IP: 86.54.28.49"}` (both measured live 2026-08-29). One pattern covers both.
BLOCKED_IP_PATTERN = re.compile(r"IP:\s*([0-9a-fA-F.:]+)")
#: The bodies are ~90 bytes. Anything longer is not one of them, and a 403 that served a
#: whole page should not cost a scan of it.
BLOCKED_BODY_SCAN_CHARS = 400


class MarketplaceBlockedError(Exception):
    """Raised when the marketplace refuses the current egress IP.

    Not Bazos-specific despite only the two Bazos scrapers raising it today: the runner
    catches it generically and answers by rotating the circuit and retrying, which is what
    Vinted and Sbazar will need too. See `ScrapeRunner._run_query_with_rotation`.

    403 is the only block status confirmed live on Bazos (nginx-level deny, path-scoped);
    the API scraper's 429 handling is defensive, so the message names both without
    claiming either.

    `exit_ip` is the egress the *marketplace* saw, and it is the only trustworthy source
    for that: the Tor proxy isolates circuits per destination host, so asking an IP-echo
    service answers about a different circuit entirely (see `IPChanger.get_current_ip`).
    Empty when the body did not name one.
    """

    def __init__(
        self,
        message: str = "Marketplace returned 403/429 for the current IP",
        exit_ip: str = "",
    ):
        super().__init__(message)
        self.exit_ip = exit_ip

    @classmethod
    def from_response(cls, response: Response) -> "MarketplaceBlockedError":
        """Build the error from a block response, lifting the exit IP out of its body.

        The message is deliberately left at the default rather than made to include the
        IP: `QueryRun.error` stores `f"{type(e).__name__}: {e}"`, and an IP in there would
        split what is one failure mode into a few hundred one-row groups. The IP belongs
        in `QueryRun.exit_ip`, which is indexed for exactly that grouping.
        """
        return cls(exit_ip=parse_blocked_exit_ip(response.text))


def parse_blocked_exit_ip(body: str) -> str:
    """The IP a block response names, or "" if it names none we can trust.

    Validated rather than taken at face value: the pattern is loose enough to match
    prose, and `QueryRun.exit_ip` is a 45-char column whose whole purpose is being
    grouped on.

    A match that fails validation is logged rather than dropped quietly. It is otherwise
    indistinguishable from a body naming no IP at all, so a body-format drift would show
    up only as the column silently going empty across every attempt.
    """
    match = BLOCKED_IP_PATTERN.search(body[:BLOCKED_BODY_SCAN_CHARS])
    if match is None:
        return ""
    # `.rstrip(".")` and not `.rstrip(".:")`: the pattern is greedy and `.` is the most
    # likely sentence terminator to follow the IP, but `2001:db8::` ends in colons legally.
    candidate = match.group(1).rstrip(".")
    try:
        return str(ip_address(candidate))
    except ValueError:
        logger.warning("Block body named an unparseable IP: %r", match.group(1))
        return ""
