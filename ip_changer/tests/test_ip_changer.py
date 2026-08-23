from unittest.mock import MagicMock, patch

import pytest
import requests
from stem import Signal

from ip_changer.dummy import DummyIPChanger
from ip_changer.ip_changer import IPChanger
from ip_changer.tor import MAX_RENEW_ATTEMPTS, TorIPChanger


class StubIPChanger(IPChanger):
    """Minimal concrete IPChanger for testing base class methods."""
    def renew_session(self):
        self.session = MagicMock()

    def renew_ip(self):
        pass

    def renew_ip_and_check_new(self) -> str:
        return "1.2.3.4"


# --- DummyIPChanger ---

def test_dummy_session_is_a_real_requests_session():
    changer = DummyIPChanger()
    assert isinstance(changer.session, requests.Session)


def test_dummy_check_ip_local_always_false():
    assert DummyIPChanger().check_ip_local() is False


def test_get_current_ip_strips_whitespace():
    changer = StubIPChanger()
    changer.session.get.return_value = MagicMock(text="1.2.3.4\n")
    assert changer.get_current_ip() == "1.2.3.4"


def test_check_ip_local_true_when_in_subnet(settings):
    settings.LOCAL_IP_SUBNET = "192.168.1.0/24"
    changer = StubIPChanger()
    changer.session.get.return_value = MagicMock(text="192.168.1.100\n")
    assert changer.check_ip_local() is True


def test_check_ip_local_false_when_outside_subnet(settings):
    settings.LOCAL_IP_SUBNET = "192.168.1.0/24"
    changer = StubIPChanger()
    changer.session.get.return_value = MagicMock(text="8.8.8.8\n")
    assert changer.check_ip_local() is False


# --- TorIPChanger ---

@pytest.fixture
def tor_changer():
    with patch.object(TorIPChanger, "renew_session"):
        changer = TorIPChanger()
    changer.session = MagicMock()
    return changer


def test_tor_renew_ip_sends_newnym_signal(tor_changer):
    with patch("ip_changer.tor.socket.gethostbyname", return_value="172.18.0.5"), \
         patch("ip_changer.tor.Controller") as mock_controller_cls:
        mock_controller = MagicMock()
        mock_controller_cls.from_port.return_value.__enter__.return_value = mock_controller
        tor_changer.renew_ip()
    mock_controller_cls.from_port.assert_called_once_with(address="172.18.0.5", port=9051)
    mock_controller.signal.assert_called_once_with(Signal.NEWNYM)


def test_tor_renew_session_sets_socks5_proxies():
    with patch.object(TorIPChanger, "renew_session"):
        changer = TorIPChanger()
    changer.renew_session()
    assert changer.session.proxies["http"].startswith("socks5h://")
    assert changer.session.proxies["https"].startswith("socks5h://")


def test_tor_skip_1st_renew_returns_current_ip_without_rotating(tor_changer):
    tor_changer.skip_1st_renew = True
    tor_changer.session.get.return_value = MagicMock(text="5.5.5.5\n")
    result = tor_changer.renew_ip_and_check_new()
    assert result == "5.5.5.5"
    assert tor_changer.skip_1st_renew is False


def test_tor_skip_1st_renew_does_not_call_renew_ip(tor_changer):
    tor_changer.skip_1st_renew = True
    tor_changer.session.get.return_value = MagicMock(text="5.5.5.5\n")
    with patch.object(tor_changer, "renew_ip") as mock_renew:
        tor_changer.renew_ip_and_check_new()
    mock_renew.assert_not_called()


def test_tor_renew_signals_newnym_on_every_round_not_just_once(tor_changer):
    """Tor rate-limits NEWNYM to ~1/10 s and drops the rest. The old loop signalled once
    and then only polled, so a dropped signal meant polling a circuit that could never
    change — an unbounded spin on the blocked exit.
    """
    ips = iter(["1.1.1.1", "1.1.1.1", "1.1.1.1", "9.9.9.9"])
    tor_changer.get_current_ip = MagicMock(side_effect=lambda: next(ips))

    with patch.object(tor_changer, "renew_ip") as mock_renew, \
         patch("ip_changer.tor.sleep"):
        result = tor_changer.renew_ip_and_check_new()

    assert result == "9.9.9.9"
    assert mock_renew.call_count == 3


def test_tor_renew_gives_up_after_max_attempts_and_reports_the_unchanged_ip(tor_changer):
    """Bounded, and honest about failing: ScrapeRunner.change_ip compares the result to the
    old IP to decide whether retrying the query is worth anything.
    """
    tor_changer.get_current_ip = MagicMock(return_value="1.1.1.1")

    with patch.object(tor_changer, "renew_ip") as mock_renew, \
         patch("ip_changer.tor.sleep"):
        result = tor_changer.renew_ip_and_check_new()

    assert result == "1.1.1.1"
    assert mock_renew.call_count == MAX_RENEW_ATTEMPTS
