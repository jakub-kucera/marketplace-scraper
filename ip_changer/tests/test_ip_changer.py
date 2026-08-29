from unittest.mock import MagicMock, patch

import pytest
import requests
from django.conf import settings
from stem import Signal

from ip_changer.dummy import DummyIPChanger
from ip_changer.ip_changer import IPChanger
from ip_changer.tor import TorIPChanger, tor_proxies


class StubIPChanger(IPChanger):
    """Minimal concrete IPChanger for testing base class methods."""
    def renew_session(self):
        self.session = MagicMock()

    def rotate_circuit(self) -> bool:
        return True


# --- DummyIPChanger ---

def test_dummy_session_is_a_real_requests_session():
    changer = DummyIPChanger()
    assert isinstance(changer.session, requests.Session)


def test_dummy_check_ip_local_always_false():
    assert DummyIPChanger().check_ip_local() is False


def test_dummy_reports_that_it_cannot_rotate():
    """One egress, no circuits — the runner must stop retrying rather than re-run the
    query against the same IP that just blocked it."""
    assert DummyIPChanger().rotate_circuit() is False


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
    """Not on the retry path any more, but still the coarse manual reset."""
    with patch("ip_changer.tor.socket.gethostbyname", return_value="172.18.0.5"), \
         patch("ip_changer.tor.Controller") as mock_controller_cls:
        mock_controller = MagicMock()
        mock_controller_cls.from_port.return_value.__enter__.return_value = mock_controller
        tor_changer.renew_ip()
    mock_controller_cls.from_port.assert_called_once_with(address="172.18.0.5", port=9051)
    mock_controller.signal.assert_called_once_with(Signal.NEWNYM)


def test_tor_session_carries_socks_credentials_pinning_one_circuit():
    """The credentials are the mechanism: Tor's IsolateSOCKSAuth gives each distinct
    username its own circuit, so the username *is* the circuit handle."""
    changer = TorIPChanger()

    for scheme in ("http", "https"):
        proxy = changer.session.proxies[scheme]
        assert proxy.startswith("socks5h://")
        assert f"{changer.circuit_id}:x@" in proxy


def test_tor_rotate_circuit_swaps_in_a_new_credential_and_session():
    changer = TorIPChanger()
    before_id, before_session = changer.circuit_id, changer.session

    assert changer.rotate_circuit() is True

    assert changer.circuit_id != before_id
    assert changer.session is not before_session
    assert f"{changer.circuit_id}:x@" in changer.session.proxies["https"]


def test_tor_rotate_circuit_sends_no_control_port_signal():
    """The point of the change: rotation is a local credential swap, so it costs no
    NEWNYM round trip and no rate-limit wait. Tor builds the circuit on the next request.
    """
    changer = TorIPChanger()

    with patch("ip_changer.tor.Controller") as mock_controller_cls, \
         patch("ip_changer.tor.socket.gethostbyname") as mock_resolve:
        changer.rotate_circuit()

    mock_controller_cls.from_port.assert_not_called()
    mock_resolve.assert_not_called()


def test_tor_rotate_circuit_never_repeats_a_credential():
    changer = TorIPChanger()

    ids = {changer.circuit_id}
    for _ in range(20):
        changer.rotate_circuit()
        ids.add(changer.circuit_id)

    assert len(ids) == 21


def test_unauthenticated_proxies_have_no_credentials():
    """`PROXIES` is the scrapers' no-session fallback: nothing there rotates, so it must
    not claim a circuit of its own."""
    assert tor_proxies()["https"] == f"socks5h://{settings.TOR_PROXY_IP}:9050"
