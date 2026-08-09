import logging
from abc import ABC, abstractmethod
from ipaddress import ip_address, ip_network
from typing import Callable, Optional

import requests

from django.conf import settings

from bazos.const import BAZOS_BLACKLIST_CHECK_URL, MAX_ATTEMPTS
from bazos.exceptions import BazosBlacklistedError

logger = logging.getLogger(__name__)


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
        r = self.session.get('https://icanhazip.com')
        return r.text.strip()

    def check_bazos_blacklisted(self, url: str = BAZOS_BLACKLIST_CHECK_URL) -> bool:
        r = self.session.get(url)
        return r.status_code == 403

    def check_ip_local(self) -> bool:
        return ip_address(self.get_current_ip()) in self.local_network

    def renew_ip_bazos_ok(
        self,
        url,
        is_blacklisted: Optional[Callable[[str], bool]] = None,
        max_attempts: int = MAX_ATTEMPTS,
    ) -> str:
        is_blacklisted = is_blacklisted or self.check_bazos_blacklisted
        for attempt in range(1, max_attempts + 1):
            new_ip = self.renew_ip_and_check_new()
            if not is_blacklisted(url):
                logger.info("BAZOS OK: new IP %s", new_ip)
                return new_ip
            logger.warning("BAZOS BLACKLISTED: new IP %s, retrying (%d/%d)", new_ip, attempt, max_attempts)
        raise BazosBlacklistedError(f"Still blacklisted after {max_attempts} IP rotation attempts")
