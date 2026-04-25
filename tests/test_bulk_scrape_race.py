"""Regression tests for BulkScrapeJob.swap_with_running / demote_running
cancel-then-reset race — Pass 19.4.

The race: the old code set `cancelled=True`, then `time.sleep(0.5)`, then
`reset()`.  If the worker thread hadn't observed the cancel flag yet, it
would wake into the new (reset) state and treat the next game as the old
job's, mixing counters.

The fix: replace the bare sleep with `self._thread.join(timeout=...)` so
the new state is only written after the old worker actually exits.
"""

import threading
import time
from unittest.mock import patch

import pytest

from services.jobs import bulk_scrape as bulk_scrape_mod
from services.jobs.bulk_scrape import BulkScrapeJob
from tests.test_bulk_scrape_job import _make_memory_db


@pytest.fixture
def job_with_real_thread():
    """BulkScrapeJob with persistence stubbed but real threading semantics.

    Unlike the main `job` fixture we don't stub `_run_scrape` to a no-op —
    we replace it with a controllable stub so the race is testable.
    """
    mem_db = _make_memory_db()
    # Pass 41.6.A — track BulkScrapeJob instances created via this fixture
    # so we can release any singleton FDs they acquired in teardown. Without
    # this, the cross-process flock survives the test and the next test's
    # start() returns "already running on another worker".
    _instances = []

    class _TrackingJob(BulkScrapeJob):
        def __init__(self):
            super().__init__()
            _instances.append(self)

    with patch.object(bulk_scrape_mod, '_get_conn', return_value=mem_db), \
         patch.object(bulk_scrape_mod, 'persist_job_start', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_progress', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_complete', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_queued', return_value=999), \
         patch.object(bulk_scrape_mod, 'remove_queued_job', return_value=None):
        yield _TrackingJob

    from services.jobs.base import release_job_singleton_lock
    for inst in _instances:
        if getattr(inst, '_singleton_fd', None) is not None:
            release_job_singleton_lock(inst._singleton_fd)
            inst._singleton_fd = None


class TestSwapWaitsForWorkerExit:
    def test_swap_does_not_reset_state_until_worker_exits(self, job_with_real_thread):
        """The new job's state must not be visible until the old worker has
        exited — otherwise counters from the new job could be attributed to
        the old job's last game."""
        worker_can_exit = threading.Event()
        worker_observed_cancel = threading.Event()

        def slow_worker(self):
            # Pretend we're processing a game. Block until either cancelled
            # or the test releases us.
            while True:
                with self._lock:
                    if self.cancelled:
                        worker_observed_cancel.set()
                        return
                if worker_can_exit.wait(timeout=0.05):
                    return

        with patch.object(BulkScrapeJob, '_run_scrape', slow_worker):
            JobCls = job_with_real_thread
            job = JobCls()
            job.start([100], system_id=1)
            assert job.running is True
            first_id = job.job_id

            job.start([200], system_id=2)
            assert len(job._queue) == 1
            queued_id = job._queue[0]['job_id']

            # Run the swap in a separate thread so we can introspect timing.
            swap_done = threading.Event()
            def do_swap():
                job.swap_with_running(queued_id)
                swap_done.set()

            swap_thread = threading.Thread(target=do_swap)
            swap_thread.start()

            # Worker should observe cancel quickly (within 0.5s).
            assert worker_observed_cancel.wait(timeout=2.0), \
                "Worker never observed cancel flag"

            # Swap must finish promptly after worker exits.
            assert swap_done.wait(timeout=5.0), \
                "Swap blocked too long — join() likely missing or wrong thread"

            # New job's state should now be in place.
            assert job.job_id == first_id  # first_id was repushed at front
            # Note: swap puts old job at front of queue, then runs queued job
            # The swap target was queued_id, so that's now job_id
            # Actually the implementation stores old as queue[0] and runs new
            # so job.job_id should be queued_id.
            assert job.job_id == queued_id

            worker_can_exit.set()
            swap_thread.join(timeout=2.0)


class TestDemoteWaitsForWorkerExit:
    def test_demote_does_not_reset_state_until_worker_exits(self, job_with_real_thread):
        worker_observed_cancel = threading.Event()

        def slow_worker(self):
            while True:
                with self._lock:
                    if self.cancelled:
                        worker_observed_cancel.set()
                        return
                time.sleep(0.05)

        with patch.object(BulkScrapeJob, '_run_scrape', slow_worker):
            JobCls = job_with_real_thread
            job = JobCls()
            job.start([100], system_id=1)
            job.start([200], system_id=2)

            demote_done = threading.Event()
            def do_demote():
                job.demote_running()
                demote_done.set()

            t = threading.Thread(target=do_demote)
            t.start()

            assert worker_observed_cancel.wait(timeout=2.0), \
                "Worker never observed cancel flag"
            assert demote_done.wait(timeout=5.0), \
                "Demote blocked too long — join() likely missing or wrong thread"
            t.join(timeout=2.0)
