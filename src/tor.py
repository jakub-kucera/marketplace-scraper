from time import sleep

import requests
import requests_random_user_agent
from stem import Signal
from stem.control import Controller

from settings import SETTINGS


PROXIES = {
    'http': f'socks5h://{SETTINGS.TOR_PROXY_IP}:9050',
    'https': f'socks5h://{SETTINGS.TOR_PROXY_IP}:9050'
}


class IPChanger:
    def __init__(self, skip_1st_renew=False):
        self.skip_1st_renew = skip_1st_renew
        self.renew_session()

    def renew_session(self):
        self.session = requests.Session()
        self.session.proxies = PROXIES

    def get_current_ip(self) -> str:
        r = self.session.get('https://icanhazip.com')
        return r.text.strip()

    def renew_tor_ip(self):
        with Controller.from_port(port=9051) as controller:
            controller.authenticate(password=SETTINGS.TOR_PROXY_PASSWORD)
            controller.signal(Signal.NEWNYM)

    def check_bazos_blacklisted(self) -> bool:
        r = self.session.get("https://bazos.cz")
        return r.status_code == 403

    def renew_ip_and_check_new(self) -> str:
        old_ip = self.get_current_ip()
        print(f"Old IP: {old_ip}")

        if self.skip_1st_renew:
            self.skip_1st_renew = False
            print("Skipping 1st renew")
            return old_ip

        self.renew_tor_ip()
        while True:
            self.renew_session()
            new_ip = self.get_current_ip()
            if old_ip != new_ip:
                print(f"New IP: {new_ip}")
                return new_ip
            sleep(1)

    def renew_ip_bazos_ok(self):
        while True:
            new_ip = self.renew_ip_and_check_new()
            if not self.check_bazos_blacklisted():
                print(f"BAZOS OK: New IP: {new_ip}")
                return new_ip
            print(f"BAZOS BLACKLISTED: New IP: {new_ip}")


def main():
    ip_changer = IPChanger()
    ip_changer.renew_ip_bazos_ok()


if __name__ == "__main__":
    main()
#
# def get_current_ip() -> str:
#     session = requests.session()
#
#     # TO Request URL with SOCKS over TOR
#     session.proxies = PROXIES
#     # try:
#     r = session.get('https://icanhazip.com')
#         # r = session.get('http://httpbin.org/ip')
#     # except Exception as e:
#     #     print(str(e))
#     # else:
#     return r.text.strip()


# def renew_tor_ip():
#     with Controller.from_port(port=9051) as controller:
#         controller.authenticate(password=SETTINGS.TOR_PROXY_PASSWORD)
#         controller.signal(Signal.NEWNYM)


# def renew_ip_and_check() -> str:
#     old_ip = get_current_ip()
#     # print(f"Old IP: {old_ip}")
#     renew_tor_ip()
#     while True:  # TODO improve
#         new_ip = get_current_ip()
#         if old_ip != new_ip:
#             # print(f"New IP: {new_ip}")
#             return new_ip
#         sleep(1)