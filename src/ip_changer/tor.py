from time import sleep

import requests
import requests_random_user_agent  # type: ignore
from stem import Signal
from stem.control import Controller

from settings import SETTINGS
from src.ip_changer.ip_changer import IPChanger

PROXIES = {
    'http': f'socks5h://{SETTINGS.TOR_PROXY_IP}:9050',
    'https': f'socks5h://{SETTINGS.TOR_PROXY_IP}:9050'
}


class TorIPChanger(IPChanger):
    # def __init__(self, skip_1st_renew=False):
    #     super().__init__(skip_1st_renew=skip_1st_renew)

    def renew_session(self):
        self.session = requests.Session()
        self.session.proxies = PROXIES

    def renew_ip(self):
        with Controller.from_port(port=9051) as controller:
            controller.authenticate(password=SETTINGS.TOR_PROXY_PASSWORD)
            controller.signal(Signal.NEWNYM)

    def renew_ip_and_check_new(self) -> str:
        old_ip = self.get_current_ip()
        print(f"Old IP: {old_ip}")

        if self.skip_1st_renew:
            self.skip_1st_renew = False
            print("Skipping 1st renew")
            return old_ip

        self.renew_ip()
        while True:
            self.renew_session()
            new_ip = self.get_current_ip()
            if old_ip != new_ip:
                print(f"New IP: {new_ip}")
                return new_ip
            sleep(1)

    # def renew_ip_bazos_ok(self):
    #     while True:
    #         new_ip = self.renew_ip_and_check_new()
    #         if not self.check_bazos_blacklisted():
    #             print(f"BAZOS OK: New IP: {new_ip}")
    #             return new_ip
    #         print(f"BAZOS BLACKLISTED: New IP: {new_ip}")
