import socket
from time import sleep
import requests
import requests_random_user_agent  # type: ignore
from stem import Signal
from stem.control import Controller
from django.conf import settings

from ip_changer.ip_changer import IPChanger

PROXIES = {
    'http': f'socks5h://{settings.TOR_PROXY_IP}:9050',
    'https': f'socks5h://{settings.TOR_PROXY_IP}:9050'
}


class TorIPChanger(IPChanger):
    def __init__(self, skip_1st_renew=False):
        super().__init__(skip_1st_renew=skip_1st_renew)

    def renew_session(self):
        self.session = requests.Session()
        self.session.proxies = PROXIES

    def renew_ip(self):
        address = socket.gethostbyname(settings.TOR_PROXY_IP)
        with Controller.from_port(address=address, port=9051) as controller:
            controller.authenticate(password=settings.TOR_PROXY_PASSWORD)
            controller.signal(Signal.NEWNYM)

    def renew_ip_and_check_new(self) -> str:
        old_ip = self.get_current_ip()
        print(f"Old IP: {old_ip}")

        if self.skip_1st_renew:
            self.skip_1st_renew = False
            print("Skipping 1st renew")
            return old_ip

        self.renew_ip()
        sleep(5)  # give Tor time to establish the new circuit before polling
        while True:
            self.renew_session()
            new_ip = self.get_current_ip()
            if old_ip != new_ip:
                print(f"New IP: {new_ip}")
                return new_ip
            else:
                print(f"DID NOT CHANGE IP: {new_ip}")
            sleep(5)
