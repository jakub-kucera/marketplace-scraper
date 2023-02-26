from abc import ABC, abstractmethod
from ipaddress import ip_address, ip_network

import requests

from django.conf import settings

from bazos.const import BAZOS_BLACKLIST_CHECK_URL


class IPChanger(ABC):
    def __init__(self, skip_1st_renew=False):
        self.skip_1st_renew = skip_1st_renew
        self.local_network = ip_network(settings.LOCAL_IP_SUBNET)
        self.session: requests.Session | None = None
        self.renew_session()

    @abstractmethod
    def renew_session(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def renew_ip(self) -> None:
        raise NotImplementedError

    @abstractmethod
    def renew_ip_and_check_new(self) -> str:
        raise NotImplementedError

    def get_current_ip(self) -> str:
        r = self.session.get('https://icanhazip.com')
        # return ip_address(r.text.strip())
        return r.text.strip()

    def check_bazos_blacklisted(self, url: str = BAZOS_BLACKLIST_CHECK_URL) -> bool:
        # r = self.session.get("https://bazos.cz")
        r = self.session.get(url)

        return r.status_code == 403

    def check_ip_local(self) -> bool:
        return ip_address(self.get_current_ip()) in self.local_network

    def renew_ip_bazos_ok(self, url) -> str:
        while True:
            new_ip = self.renew_ip_and_check_new()
            if not self.check_bazos_blacklisted(url):
                print(f"BAZOS OK: New IP: {new_ip}")
                return new_ip
            print(f"BAZOS BLACKLISTED: New IP: {new_ip}")
