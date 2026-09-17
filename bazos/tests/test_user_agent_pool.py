"""The rotation pool must not contain phone/tablet agents.

Bazos serves a *different DOM* to mobile User-Agents — measured 2026-09-17, same circuit,
seconds apart: a desktop agent got 20 parseable rows, an iPhone and an Android agent each got
20 rows with no `inzeratycena` at all. `BazosScraper._parse_product` is written against the
desktop markup, so the first row raises `AttributeError` and takes the whole page with it.

The pool is third-party data (`requests_random_user_agent`), so these assert on **our filtered
output and our filter**, never on the library's contents — a library update changing its list
must not turn this red for the wrong reason.
"""
import pytest

from ip_changer.tor import MOBILE_UA_MARKERS, drop_mobile_user_agents

DESKTOP = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36"
IPHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Version/17.0 Mobile/15E148 Safari/604.1"
ANDROID = "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 Chrome/131.0.0.0 Mobile Safari/537.36"


def is_mobile(user_agent: str) -> bool:
    return any(marker in user_agent for marker in MOBILE_UA_MARKERS)


# ---------------------------------------------------------------------------
# The live pool, after `ip_changer.tor` has been imported
# ---------------------------------------------------------------------------

def test_live_pool_has_no_mobile_agents():
    import requests_random_user_agent

    offenders = [ua for ua in requests_random_user_agent.USER_AGENTS if is_mobile(ua)]

    assert offenders == [], f"mobile agents still in the pool: {offenders}"


def test_live_pool_is_not_empty():
    """`random.choice([])` raises inside the patched `default_user_agent`, which would break
    every request rather than the ~3% this filter is removing."""
    import requests_random_user_agent

    assert len(requests_random_user_agent.USER_AGENTS) > 0


def test_the_patched_default_user_agent_is_a_desktop_agent():
    """The end-to-end property: what `requests` actually puts on the wire."""
    import requests.utils

    for _ in range(50):   # it draws randomly per call, so sample
        assert not is_mobile(requests.utils.default_user_agent())


# ---------------------------------------------------------------------------
# The filter itself, against a synthetic pool
# ---------------------------------------------------------------------------

@pytest.fixture
def pool(monkeypatch):
    """Swap in a pool we control, so these tests never depend on the library's list."""
    import requests_random_user_agent

    agents = [DESKTOP, IPHONE, ANDROID, DESKTOP + " (2)"]
    monkeypatch.setattr(requests_random_user_agent, "USER_AGENTS", agents)
    return agents


def test_filter_drops_mobile_and_keeps_desktop(pool):
    dropped = drop_mobile_user_agents()

    assert dropped == 2
    assert pool == [DESKTOP, DESKTOP + " (2)"]


def test_filter_mutates_in_place(pool):
    """The library's patch resolves `USER_AGENTS` from its own module globals per call, so
    the list object has to be updated rather than replaced."""
    original = pool

    drop_mobile_user_agents()

    assert original is pool and IPHONE not in original


def test_filter_is_idempotent(pool):
    drop_mobile_user_agents()

    assert drop_mobile_user_agents() == 0
    assert pool == [DESKTOP, DESKTOP + " (2)"]


def test_filter_refuses_to_empty_an_all_mobile_pool(monkeypatch):
    """Better 3% unparseable pages than 100% failed requests.

    Asserts against the logger object rather than `caplog`: the `ip_changer` logger is
    configured with `propagate: False`, so its records never reach the root handler pytest
    captures on.
    """
    import ip_changer.tor
    import requests_random_user_agent

    agents = [IPHONE, ANDROID]
    monkeypatch.setattr(requests_random_user_agent, "USER_AGENTS", agents)
    reported: list[tuple] = []
    monkeypatch.setattr(ip_changer.tor.logger, "error", lambda *a, **k: reported.append(a))

    assert drop_mobile_user_agents() == 0
    assert agents == [IPHONE, ANDROID]
    assert reported, "an all-mobile pool must be reported, not silently accepted"
