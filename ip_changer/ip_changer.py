import logging
from abc import ABC, abstractmethod
from ipaddress import ip_address, ip_network

import requests

from django.conf import settings

logger = logging.getLogger(__name__)

#: Every call here goes through Tor, where an unreachable host usually means a stalled
#: socket rather than a refused connection. Without this the caller's `except` guards
#: catch nothing and the scraping pass hangs indefinitely.
IP_LOOKUP_TIMEOUT = 10


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

    def get_current_ip(self) -> str:
        r = self.session.get('https://icanhazip.com', timeout=IP_LOOKUP_TIMEOUT)
        return r.text.strip()

    def check_ip_local(self) -> bool:
        return ip_address(self.get_current_ip()) in self.local_network
