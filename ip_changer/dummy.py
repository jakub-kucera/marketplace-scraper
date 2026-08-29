import requests

from ip_changer.ip_changer import IPChanger


class DummyIPChanger(IPChanger):
    def renew_session(self):
        self.session = requests.Session()

    def rotate_circuit(self) -> bool:
        """False: there is one egress and no circuits to draw.

        Retrying a blocked request on the same IP cannot succeed, so the runner is told
        to stop rather than spend its whole retry budget proving that.
        """
        return False

    def check_ip_local(self) -> bool:
        return False
