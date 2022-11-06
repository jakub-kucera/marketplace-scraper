from abc import ABC, abstractmethod
from ipaddress import ip_address, ip_network

import requests

from settings import SETTINGS


class IPChanger(ABC):
    def __init__(self, skip_1st_renew=False):
        self.skip_1st_renew = skip_1st_renew
        self.local_network = ip_network(SETTINGS.LOCAL_IP_SUBNET)
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

    def check_bazos_blacklisted(self) -> bool:
        r = self.session.get("https://bazos.cz")
        return r.status_code == 403

    def check_ip_local(self) -> bool:
        return ip_address(self.get_current_ip()) in self.local_network

    def renew_ip_bazos_ok(self) -> str:
        while True:
            new_ip = self.renew_ip_and_check_new()
            if not self.check_bazos_blacklisted():
                print(f"BAZOS OK: New IP: {new_ip}")
                return new_ip
            print(f"BAZOS BLACKLISTED: New IP: {new_ip}")
