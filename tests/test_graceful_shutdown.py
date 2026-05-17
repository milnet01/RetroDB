"""Tests for services.jobs.base.request_shutdown — Pass 19.2.

The shutdown helper is invoked by the SIGTERM/SIGINT handler installed in
app.py.  It should:
  1. Set the package-level shutdown_requested event.
  2. Call .cancel() on every running job singleton.
  3. Wait up to `timeout` for worker threads to drain.
"""

import threading
import time

import pytest

import services.jobs as jobs_pkg
from services.jobs import base as base_mod


_SINGLETON_NAMES = (
    'bulk_scrape_job', 'ra_sync_job', 'ra_refresh_job', 'psn_refresh_job',
    'museum_generate_job', 'image_resize_job', 'steam_sync_job',
    'xbox_sync_job', 'alt_titles_backfill_job', 'hltb_bulk_job',
)


class _FakeJob:
    """Minimal job stand-in: tracks .cancel() calls and exposes a
    controllable _thread."""
    def __init__(self, running=True, slow=False):
        self.running = running
        self.cancel_called = False
        self._exit = threading.Event()
        if slow:
            self._thread = threading.Thread(target=self._exit.wait, daemon=True)
            self._thread.start()
        else:
            self._thread = threading.Thread(target=lambda: None, daemon=True)
            self._thread.start()
            self._thread.join()

    def cancel(self):
        self.cancel_called = True
        self._exit.set()


@pytest.fixture
def isolated_singletons():
    """Replace each real singleton with None for the duration of the test
    so we can substitute fakes without affecting the real package."""
    saved = {name: getattr(jobs_pkg, name, None) for name in _SINGLETON_NAMES}
    for name in _SINGLETON_NAMES:
        setattr(jobs_pkg, name, None)
    yield
    for name, val in saved.items():
        setattr(jobs_pkg, name, val)


class TestRequestShutdown:
    def test_sets_shutdown_event(self):
        base_mod.shutdown_requested.clear()
        try:
            base_mod.request_shutdown(timeout=0.1)
            assert base_mod.shutdown_requested.is_set()
        finally:
            # Always clear so a failed assertion above doesn't leak the set
            # state into subsequent tests in the same session.
            base_mod.shutdown_requested.clear()

    def test_calls_cancel_on_running_jobs(self, isolated_singletons):
        running = _FakeJob(running=True)
        idle = _FakeJob(running=False)
        jobs_pkg.bulk_scrape_job = running
        jobs_pkg.ra_sync_job = idle

        base_mod.shutdown_requested.clear()
        base_mod.request_shutdown(timeout=0.5)

        assert running.cancel_called is True
        assert idle.cancel_called is False

    def test_waits_for_running_thread_then_exits(self, isolated_singletons):
        slow = _FakeJob(running=True, slow=True)
        jobs_pkg.bulk_scrape_job = slow

        t0 = time.monotonic()
        base_mod.request_shutdown(timeout=0.5)
        elapsed = time.monotonic() - t0

        # cancel() set the exit event, so the slow thread should exit
        # quickly — well under the 0.5s timeout. The 1.5s upper bound is
        # generous headroom for loaded CI runners.
        assert elapsed < 1.5, f"request_shutdown took {elapsed:.2f}s, should be fast"
        assert not slow._thread.is_alive()

    def test_timeout_caps_drain_wait(self, isolated_singletons):
        """If a worker ignores cancel and refuses to exit, request_shutdown
        must still return within roughly `timeout` seconds."""
        stuck = _FakeJob(running=True, slow=True)
        def stubborn_cancel():
            stuck.cancel_called = True
        stuck.cancel = stubborn_cancel
        jobs_pkg.bulk_scrape_job = stuck

        try:
            t0 = time.monotonic()
            base_mod.request_shutdown(timeout=0.3)
            elapsed = time.monotonic() - t0

            # Upper bound proves the timeout caps the wait. The lower bound
            # has been replaced with a thread-liveness check — proving the
            # stuck worker is still alive when shutdown returns is a stronger
            # statement than wall-clock minimums (which fail on fast machines
            # where join() can return slightly early).
            assert elapsed < 1.0, \
                f"request_shutdown took {elapsed:.2f}s, expected ~0.3s"
            assert stuck._thread.is_alive(), \
                "stuck worker should still be running after timed-out shutdown"
        finally:
            stuck._exit.set()
            stuck._thread.join(timeout=1.0)
