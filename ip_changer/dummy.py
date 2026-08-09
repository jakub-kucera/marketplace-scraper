import requests

from bazos.const import BAZOS_BLACKLIST_CHECK_URL
from ip_changer.ip_changer import IPChanger


class DummyIPChanger(IPChanger):
    def renew_session(self):
        self.session = requests.Session()

    def renew_ip(self):
        pass

    def renew_ip_and_check_new(self) -> str:
        return "Dummy IP"

    def renew_ip_bazos_ok(self, url: str, is_blacklisted=None, max_attempts=None) -> str:
        return "Dummy IP"

    def check_bazos_blacklisted(self, url: str = BAZOS_BLACKLIST_CHECK_URL) -> bool:
        return False

    def check_ip_local(self) -> bool:
        return False
