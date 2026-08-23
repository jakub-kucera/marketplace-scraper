import logging
import socket
from time import sleep
import requests
import requests_random_user_agent  # type: ignore  # noqa: F401 (side-effecting import: patches requests.Session UA)
from stem import Signal
from stem.control import Controller
from django.conf import settings

from ip_changer.ip_changer import IPChanger

logger = logging.getLogger(__name__)

PROXIES = {
    'http': f'socks5h://{settings.TOR_PROXY_IP}:9050',
    'https': f'socks5h://{settings.TOR_PROXY_IP}:9050'
}

#: Tor rate-limits NEWNYM to roughly one per 10 s and silently ignores signals sent
#: inside that window, so a shorter wait makes a re-signal a no-op rather than a retry.
NEWNYM_WAIT_SECONDS = 10
#: Bound on the rotate-and-check loop. Without one a Tor that will not hand over a new
#: exit hangs the whole scraper pass indefinitely.
MAX_RENEW_ATTEMPTS = 5


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
        logger.debug("Old IP: %s", old_ip)

        if self.skip_1st_renew:
            self.skip_1st_renew = False
            logger.debug("Skipping 1st renew")
            return old_ip

        for attempt in range(1, MAX_RENEW_ATTEMPTS + 1):
            # Re-signal on every round rather than signalling once and then polling: if
            # Tor drops the first NEWNYM (it rate-limits them), polling the same circuit
            # can never make it change, so the old loop spun forever on that IP.
            self.renew_ip()
            sleep(NEWNYM_WAIT_SECONDS)  # let the new circuit come up, and clear the rate limit
            self.renew_session()
            new_ip = self.get_current_ip()
            if old_ip != new_ip:
                logger.info("New IP: %s", new_ip)
                return new_ip
            logger.warning(
                "NEWNYM %d/%d did not change the exit IP (%s)", attempt, MAX_RENEW_ATTEMPTS, new_ip
            )
        logger.error(
            "Exit IP still %s after %d NEWNYM attempts, giving up on rotation", old_ip, MAX_RENEW_ATTEMPTS
        )
        return old_ip
