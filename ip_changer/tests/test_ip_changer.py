from unittest.mock import MagicMock, patch

import pytest
import requests
from stem import Signal

from bazos.exceptions import BazosBlacklistedError
from ip_changer.dummy import DummyIPChanger
from ip_changer.ip_changer import IPChanger
from ip_changer.tor import TorIPChanger


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


def test_dummy_check_bazos_blacklisted_always_false():
    assert DummyIPChanger().check_bazos_blacklisted("http://example.com") is False


def test_dummy_check_ip_local_always_false():
    assert DummyIPChanger().check_ip_local() is False


def test_dummy_renew_ip_bazos_ok_accepts_url_and_returns_string():
    result = DummyIPChanger().renew_ip_bazos_ok("http://example.com")
    assert result == "Dummy IP"


# --- IPChanger base class (via StubIPChanger) ---

def test_check_bazos_blacklisted_true_on_403():
    changer = StubIPChanger()
    changer.session.get.return_value = MagicMock(status_code=403)
    assert changer.check_bazos_blacklisted("http://example.com") is True


def test_check_bazos_blacklisted_false_on_200():
    changer = StubIPChanger()
    changer.session.get.return_value = MagicMock(status_code=200)
    assert changer.check_bazos_blacklisted("http://example.com") is False


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


def test_renew_ip_bazos_ok_returns_ip_immediately_when_not_blacklisted():
    changer = StubIPChanger()
    changer.session.get.return_value = MagicMock(status_code=200)
    assert changer.renew_ip_bazos_ok("http://example.com") == "1.2.3.4"


def test_renew_ip_bazos_ok_retries_until_not_blacklisted():
    changer = StubIPChanger()
    changer.session.get.side_effect = [
        MagicMock(status_code=403),
        MagicMock(status_code=403),
        MagicMock(status_code=200),
    ]
    result = changer.renew_ip_bazos_ok("http://example.com")
    assert result == "1.2.3.4"
    assert changer.session.get.call_count == 3


def test_renew_ip_bazos_ok_raises_after_max_attempts_exhausted():
    """A permanently-blacklisted pool must not spin forever (P20 part b)."""
    changer = StubIPChanger()
    changer.session.get.return_value = MagicMock(status_code=403)
    with pytest.raises(BazosBlacklistedError):
        changer.renew_ip_bazos_ok("http://example.com", max_attempts=3)
    assert changer.session.get.call_count == 3


def test_renew_ip_bazos_ok_uses_custom_is_blacklisted_check():
    """A caller can target a different surface than the default HTML check
    (e.g. BazosApiScraper.check_blacklisted for the hidden API)."""
    changer = StubIPChanger()
    is_blacklisted = MagicMock(side_effect=[True, False])
    result = changer.renew_ip_bazos_ok("http://example.com", is_blacklisted=is_blacklisted)
    assert result == "1.2.3.4"
    assert is_blacklisted.call_count == 2
    changer.session.get.assert_not_called()


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
