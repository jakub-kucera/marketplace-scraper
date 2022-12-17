from src.ip_changer.ip_changer import IPChanger


class OpenVPNIPChanger(IPChanger):
    def renew_session(self):
        pass

    def renew_ip(self):
        pass

    def renew_ip_and_check_new(self) -> str:
        pass
