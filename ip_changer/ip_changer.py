import logging
from abc import ABC, abstractmethod
from ipaddress import ip_address, ip_network

import requests

from django.conf import settings

logger = logging.getLogger(__name__)

#: (connect, read). Every call here goes through Tor, where an unreachable host usually
#: means a stalled socket rather than a refused connection — without a timeout the caller's
#: `except` guards catch nothing and the pass hangs indefinitely. The connect budget has to
#: cover Tor *circuit construction*, not just a TCP handshake: a flat 10 s was too tight
#: right after a NEWNYM and timed out in production on 2026-08-23.
IP_LOOKUP_TIMEOUT = (20, 15)
#: A single timed-out lookup is usually one bad circuit, not a broken Tor.
IP_LOOKUP_ATTEMPTS = 3


class IPChanger(ABC):
    def __init__(self, skip_1st_renew=False):
        self.skip_1st_renew = skip_1st_renew
        self.local_network = ip_network(settings.LOCAL_IP_SUBNET)
        self.session: requests.Session | None = None
        self.renew_session()

    @abstractmethod
    def renew_session(self) -> None: ...

    @abstractmethod
    def renew_ip(self) -> None: ...

    @abstractmethod
    def renew_ip_and_check_new(self) -> str: ...

    def get_current_ip(self, attempts: int = IP_LOOKUP_ATTEMPTS) -> str:
        """Look up the current egress IP. Raises if every attempt fails.

        Callers that must not die with it use `try_get_current_ip`; `check_ip_local`
        deliberately still raises, because "we cannot see our own egress" means the
        transport is broken and the caller should stand down rather than scrape on.
        """
        # A real exception rather than `assert last_error is not None`: under `python -O`
        # the assert is stripped and `raise None` is a TypeError.
        last_error: Exception = RuntimeError(f"no IP lookup attempted (attempts={attempts})")
        for attempt in range(1, attempts + 1):
            try:
                r = self.session.get('https://icanhazip.com', timeout=IP_LOOKUP_TIMEOUT)
                return r.text.strip()
            except requests.RequestException as e:
                last_error = e
                logger.warning("Exit IP lookup failed (attempt %d/%d): %s", attempt, attempts, e)
        raise last_error

    def try_get_current_ip(self, attempts: int = 1) -> str | None:
        """`get_current_ip` for callers where not knowing is survivable.

        Defaults to a **single** attempt. Its callers are already retry loops, and three
        nested budgets multiply: 3 lookups x 5 NEWNYM rounds x MAX_BLACKLIST_RETRIES turned
        one query's rotation budget into tens of minutes, which nothing can interrupt —
        `_interruptible_sleep` and the force-run flag only apply between passes.
        """
        try:
            return self.get_current_ip(attempts=attempts)
        except requests.RequestException:
            return None

    def check_ip_local(self) -> bool:
        return ip_address(self.get_current_ip()) in self.local_network
