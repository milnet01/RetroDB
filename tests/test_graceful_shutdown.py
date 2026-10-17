"""Tests for services.jobs.base.request_shutdown — Pass 19.2.

The shutdown helper is invoked by the SIGTERM/SIGINT handler installed in
app.py.  It should:
  1. Set the package-level shutdown_requested event.
  2. Call .cancel() on every running job singleton.
  3. Wait up to `timeout` for worker threads to drain.
"""

import threading

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
    so we can substitute fakes without affecting the real package.

    Also defensively clears `base_mod.shutdown_requested` on entry AND exit
    so this fixture leaves the package in a known-clean state even if a
    previous test (or interrupted run) left the event set."""
    saved = {name: getattr(jobs_pkg, name, None) for name in _SINGLETON_NAMES}
    for name in _SINGLETON_NAMES:
        setattr(jobs_pkg, name, None)
    base_mod.shutdown_requested.clear()
    try:
        yield
    finally:
        for name, val in saved.items():
            setattr(jobs_pkg, name, val)
        base_mod.shutdown_requested.clear()


class TestRequestShutdown:
    def test_sets_shutdown_event(self, isolated_singletons):
        # `isolated_singletons` Nones out every real job singleton and
        # clears the shutdown_requested event on entry/exit, so this test
        # can't accidentally `.cancel()` a real running job in the process.
        # Every singleton is None, so there is nothing to drain: timeout=0.
        base_mod.request_shutdown(timeout=0)
        assert base_mod.shutdown_requested.is_set()

    def test_calls_cancel_on_running_jobs(self, isolated_singletons):
        # Populate EVERY singleton with a running fake — guards against a
        # future refactor that breaks the cancel path for any one of them
        # (e.g. a typo in the loop that walks _SINGLETON_NAMES). The
        # two-singleton version of this test would have missed that class
        # of regression.
        fakes = {name: _FakeJob(running=True) for name in _SINGLETON_NAMES}
        for name, fake in fakes.items():
            setattr(jobs_pkg, name, fake)

        # The fakes' threads have already exited, so no join blocks.
        base_mod.request_shutdown(timeout=0.01)

        for name, fake in fakes.items():
            assert fake.cancel_called is True, f"{name}.cancel() was not called"

    def test_waits_for_running_thread_then_exits(self, isolated_singletons):
        slow = _FakeJob(running=True, slow=True)
        jobs_pkg.bulk_scrape_job = slow

        # join() returns as soon as the thread exits, so a generous timeout
        # costs nothing on the happy path and cannot flake on a slow runner.
        base_mod.request_shutdown(timeout=5.0)
        # The thread-liveness check is the real contract: cancel() set the exit
        # event, so request_shutdown's join() must have observed the thread exit
        # before returning. A wall-clock bound on top of that is flake-bait on
        # loaded CI runners — the join semantic already pins what we care about.
        assert not slow._thread.is_alive()

    def test_timeout_caps_drain_wait(self, isolated_singletons):
        """If a worker ignores cancel and refuses to exit, request_shutdown
        must cap its wait at `timeout` seconds rather than block on the
        worker. A recording stand-in for the thread replaces a real stuck
        thread, so the test never blocks on the wall clock."""
        class _StuckThread:
            def __init__(self):
                self.join_timeouts = []

            def is_alive(self):
                return True

            def join(self, timeout=None):
                self.join_timeouts.append(timeout)

        stuck = _FakeJob(running=True)
        stuck._thread = _StuckThread()
        def stubborn_cancel():
            stuck.cancel_called = True
        stuck.cancel = stubborn_cancel
        jobs_pkg.bulk_scrape_job = stuck

        base_mod.request_shutdown(timeout=0.3)

        assert stuck.cancel_called is True
        joins = stuck._thread.join_timeouts
        assert len(joins) == 1, f"expected one bounded join, got {joins!r}"
        assert joins[0] is not None, "join() must be bounded, never unbounded"
        assert 0 < joins[0] <= 0.3, f"join timeout {joins[0]!r} exceeds the cap"
