"""Tests for the Force Run Now feature.

Covers:
- ScrapeRunner._interruptible_sleep: exits early when flag file is present
- ScrapeRunner._interruptible_sleep: sleeps full duration when flag is absent
- admin force_run_now view: creates the flag file and redirects
- admin force_run_now view: flag is deleted after _interruptible_sleep detects it
"""
import time
from unittest.mock import MagicMock, patch

from django.test import RequestFactory
from django.contrib.admin.sites import AdminSite
from django.contrib.messages.storage.fallback import FallbackStorage

from marketplace.admin import QueryAdmin
from marketplace.models import Query
from marketplace.scraping.runner import ScrapeRunner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_runner() -> ScrapeRunner:
    """Construct a ScrapeRunner bypassing __init__ — only the sleep logic is under test."""
    runner = ScrapeRunner.__new__(ScrapeRunner)
    runner.unsafe = False
    runner.discord_loggers = []
    runner.summary_senders = []
    runner.interval_multiplier = MagicMock()
    return runner


# ---------------------------------------------------------------------------
# _interruptible_sleep tests  (no DB required)
# ---------------------------------------------------------------------------

class TestInterruptibleSleep:

    def test_sleeps_full_duration_when_no_flag(self, tmp_path, settings):
        """When the flag file is absent the full sleep duration is respected."""
        settings.FORCE_RUN_FLAG_PATH = tmp_path / "force_run.flag"
        runner = make_runner()

        start = time.monotonic()
        runner._interruptible_sleep(0.1)  # 100 ms — fast but real
        elapsed = time.monotonic() - start

        assert elapsed >= 0.09, f"Sleep ended too early: {elapsed:.3f}s"

    def test_exits_early_when_flag_present(self, tmp_path, settings):
        """When the flag file exists the sleep returns before the full duration."""
        flag_path = tmp_path / "force_run.flag"
        settings.FORCE_RUN_FLAG_PATH = flag_path
        flag_path.touch()  # flag already present before sleep starts

        runner = make_runner()

        start = time.monotonic()
        # Full duration is 60 s — we expect it to exit within one 5-second tick
        with patch("marketplace.scraping.runner.sleep") as mock_sleep:
            # Make the patched sleep a no-op so the test is instant
            mock_sleep.side_effect = None
            runner._interruptible_sleep(60)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"Sleep did not exit early: {elapsed:.3f}s"

    def test_flag_is_deleted_after_early_exit(self, tmp_path, settings):
        """The flag file must be removed when the early exit is triggered."""
        flag_path = tmp_path / "force_run.flag"
        settings.FORCE_RUN_FLAG_PATH = flag_path
        flag_path.touch()

        runner = make_runner()

        with patch("marketplace.scraping.runner.sleep"):
            runner._interruptible_sleep(60)

        assert not flag_path.exists(), "Flag file was not deleted after early exit"

    def test_flag_absent_after_normal_sleep(self, tmp_path, settings):
        """No flag file should be left over after a normal (non-interrupted) sleep."""
        flag_path = tmp_path / "force_run.flag"
        settings.FORCE_RUN_FLAG_PATH = flag_path
        # flag is NOT created — normal path
        runner = make_runner()

        runner._interruptible_sleep(0.05)

        assert not flag_path.exists()


# ---------------------------------------------------------------------------
# Admin view tests  (no DB required)
# ---------------------------------------------------------------------------

def _make_request_with_messages(path="/"):
    """Build a GET request with the messages middleware attached."""
    factory = RequestFactory()
    request = factory.get(path)
    # Django messages framework requires session + message storage
    request.session = {}
    messages = FallbackStorage(request)
    request._messages = messages
    return request


class TestForceRunAdminView:

    def _get_admin(self):
        site = AdminSite()
        return QueryAdmin(Query, site)

    def test_force_run_creates_flag_file(self, tmp_path, settings):
        """Hitting the force-run view creates the sentinel flag file."""
        flag_path = tmp_path / "force_run.flag"
        settings.FORCE_RUN_FLAG_PATH = flag_path

        admin = self._get_admin()
        request = _make_request_with_messages()
        request.META["HTTP_REFERER"] = "/admin/bazos/query/"

        admin.force_run_now(request)

        assert flag_path.exists(), "Flag file was not created by force_run_now view"

    def test_force_run_redirects_to_referer(self, tmp_path, settings):
        """force_run_now redirects back to the referer URL."""
        settings.FORCE_RUN_FLAG_PATH = tmp_path / "force_run.flag"

        admin = self._get_admin()
        request = _make_request_with_messages()
        referer = "/admin/bazos/query/"
        request.META["HTTP_REFERER"] = referer

        response = admin.force_run_now(request)

        assert response.status_code == 302
        assert response["Location"] == referer

    def test_force_run_falls_back_when_no_referer(self, tmp_path, settings):
        """force_run_now falls back to '../' when HTTP_REFERER is absent."""
        settings.FORCE_RUN_FLAG_PATH = tmp_path / "force_run.flag"

        admin = self._get_admin()
        request = _make_request_with_messages()
        request.META.pop("HTTP_REFERER", None)

        response = admin.force_run_now(request)

        assert response.status_code == 302
        assert response["Location"] == "../"
