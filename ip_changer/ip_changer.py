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
#: right after a rotation and timed out in production on 2026-08-23.
IP_LOOKUP_TIMEOUT = (20, 15)
#: A single timed-out lookup is usually one bad circuit, not a broken Tor.
IP_LOOKUP_ATTEMPTS = 3


class IPChanger(ABC):
    def __init__(self):
        self.local_network = ip_network(settings.LOCAL_IP_SUBNET)
        self.session: requests.Session | None = None
        self.renew_session()

    @abstractmethod
    def renew_session(self) -> None: ...

    @abstractmethod
    def rotate_circuit(self) -> bool:
        """Move this changer's session onto a different egress, cheaply.

        Returns whether the transport can offer one at all, so a caller retrying a
        blocked request knows whether another attempt could possibly differ from the
        last. It does NOT promise the new egress is any good — only the caller's next
        real request can say that.
        """

    def get_current_ip(self, attempts: int = IP_LOOKUP_ATTEMPTS) -> str:
        """Look up the egress IP of *this* session's circuit to icanhazip.com.

        Note the destination in that sentence. The Tor proxy runs `SocksPort ...
        IsolateDestAddr`, so this answers for the icanhazip circuit and no other — it is
        NOT the IP a marketplace on a different host sees. `check_ip_local` is the only
        thing that question is still the right one for: "is *any* of our traffic leaving
        unproxied" is a property of the transport, not of one destination.

        Raises if every attempt fails, which is what `check_ip_local` wants: not being
        able to see our own egress means the transport is broken and the caller should
        stand down rather than scrape on.
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

    def check_ip_local(self) -> bool:
        return ip_address(self.get_current_ip()) in self.local_network
