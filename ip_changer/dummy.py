from src.ip_changer.ip_changer import IPChanger


class DummyIPChanger(IPChanger):
    def renew_session(self):
        pass

    def renew_ip(self):
        pass

    def renew_ip_and_check_new(self) -> str:
        pass

    def renew_ip_bazos_ok(self) -> str:
        return "Dummy IP"

    def check_bazos_blacklisted(self, url: str) -> bool:
        return False

    def check_ip_local(self) -> bool:
        return False
