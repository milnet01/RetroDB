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
from unittest.mock import patch

import pytest

from services.jobs.bulk_scrape import BulkScrapeJob
from tests._bulk_scrape_fixtures import (
    bulk_scrape_persistence_patches,
    make_memory_db,
)


@pytest.fixture
def job_with_real_thread():
    """BulkScrapeJob with persistence stubbed but real threading semantics.

    Unlike the main `job` fixture we don't stub `_run_scrape` to a no-op —
    we replace it with a controllable stub so the race is testable.
    The persistence + singleton-lock stub stanza lives in
    `tests/_bulk_scrape_fixtures.py` (test-audit c-001 MED duplication).
    """
    mem_db = make_memory_db()
    # Pass 41.6.A — track BulkScrapeJob instances created via this fixture
    # so we can release any singleton FDs they acquired in teardown. Without
    # this, the cross-process flock survives the test and the next test's
    # start() returns "already running on another worker".
    _instances = []

    class _TrackingJob(BulkScrapeJob):
        def __init__(self):
            super().__init__()
            _instances.append(self)

    with bulk_scrape_persistence_patches(mem_db):
        yield _TrackingJob

    from services.jobs.base import release_job_singleton_lock
    for inst in _instances:
        if getattr(inst, '_singleton_fd', None) is not None:
            release_job_singleton_lock(inst._singleton_fd)
            inst._singleton_fd = None


# The old code slept 0.5 s after the cancel, then reset. A worker that saw
# the cancel at once exited inside that half second, so a stub that returns on
# cancel passed against the old code too. These stubs see the cancel and then
# keep running until the test lets them go: the hand-off must wait for them.
_HELD_LONGER_THAN_OLD_SLEEP = 1.0


def _worker_that_lingers_after_cancel(observed_cancel, may_exit):
    def worker(self):
        while True:
            with self._lock:
                if self.cancelled:
                    observed_cancel.set()
                    break
            if may_exit.wait(timeout=0.05):
                return
        may_exit.wait(timeout=10.0)  # still finishing its game
    return worker


def _hand_off_waits_for_old_worker(job, hand_off, old_job_id):
    """Run hand_off in a thread while the old worker is still busy after the
    cancel; the new job's state must not appear until that worker returns."""
    observed_cancel = job._test_observed_cancel
    may_exit = job._test_may_exit
    done = threading.Event()
    t = threading.Thread(target=lambda: (hand_off(), done.set()))
    t.start()
    try:
        assert observed_cancel.wait(timeout=5.0), (
            f"Worker never observed cancel flag — job.cancelled={job.cancelled!r}")
        assert not done.wait(timeout=_HELD_LONGER_THAN_OLD_SLEEP), (
            "Hand-off finished while the old worker was still running")
        with job._lock:
            assert job.job_id == old_job_id, (
                f"New job's state written before the old worker exited: "
                f"job_id={job.job_id!r}")
    finally:
        may_exit.set()
    assert done.wait(timeout=5.0), "Hand-off never finished after the worker exited"
    t.join(timeout=2.0)


def _start_two_jobs(JobCls):
    observed_cancel, may_exit = threading.Event(), threading.Event()
    job = JobCls()
    job._test_observed_cancel, job._test_may_exit = observed_cancel, may_exit
    return job, _worker_that_lingers_after_cancel(observed_cancel, may_exit)


class TestSwapJobOrdering:
    def test_new_job_counters_start_clean_after_cancel(self, job_with_real_thread):
        """The new job's state must not be visible until the old worker has
        exited — otherwise counters from the new job could be attributed to
        the old job's last game."""
        job, worker = _start_two_jobs(job_with_real_thread)
        with patch.object(BulkScrapeJob, '_run_scrape', worker):
            job.start([100], system_id=1)
            assert job.running is True
            first_id = job.job_id
            job.start([200], system_id=2)
            assert len(job._queue) == 1
            queued_id = job._queue[0]['job_id']

            _hand_off_waits_for_old_worker(
                job, lambda: job.swap_with_running(queued_id), first_id)

            # swap_with_running puts the old job at the front of the queue and
            # makes the promoted queued_id the running job.
            assert job.job_id == queued_id
            assert job._queue and job._queue[0]['job_id'] == first_id


class TestDemoteJobOrdering:
    def test_demoted_job_state_only_resets_after_worker_exits(self, job_with_real_thread):
        job, worker = _start_two_jobs(job_with_real_thread)
        with patch.object(BulkScrapeJob, '_run_scrape', worker):
            job.start([100], system_id=1)
            first_id = job.job_id
            job.start([200], system_id=2)
            queued_id = job._queue[0]['job_id']

            _hand_off_waits_for_old_worker(job, job.demote_running, first_id)

            # demote_running promotes the next queued job to running and pushes
            # the demoted one back onto the queue.
            assert job.running is True
            assert job.job_id == queued_id
            assert [q['job_id'] for q in job._queue] == [first_id]


class TestOneWorkerAfterHandoff:
    """Pass 59.43: the old worker's exit ran the queue hand-off, which popped
    the job swap/demote had just re-queued and started it — then the handler
    started the promoted job as well. Two workers, sharing one set of counters.

    The stubs above return without the hand-off, which is how that stayed
    hidden. This stub exits the way `_run_scrape` does."""

    def _exiting_worker(self, alive):
        def worker(job):
            alive.add(threading.current_thread())
            try:
                while True:
                    with job._lock:
                        if job.cancelled:
                            break
                    threading.Event().wait(0.02)
            finally:
                alive.discard(threading.current_thread())
            # Exactly the real worker's exit path.
            finish = getattr(job, '_finish_worker', None)
            (finish or job._start_next_queued)()
        return worker

    def _stop_all(self, job, alive):
        with job._lock:
            job._queue.clear()
            job.cancelled = True
        for t in list(alive):
            t.join(timeout=2.0)

    @pytest.mark.parametrize('action', ['swap', 'demote'])
    def test_exactly_one_worker_runs(self, job_with_real_thread, action):
        alive = set()
        with patch.object(BulkScrapeJob, '_run_scrape', self._exiting_worker(alive)):
            job = job_with_real_thread()
            job.start([100], system_id=1)
            job.start([200], system_id=2)
            promoted = job._queue[0]['job_id']
            try:
                if action == 'swap':
                    assert job.swap_with_running(promoted)['success']
                else:
                    assert job.demote_running()['success']
                threading.Event().wait(0.3)
                assert len(alive) == 1, f"{len(alive)} workers running"
                # The promoted job runs; the displaced one waits in the queue.
                assert job.game_ids == [200]
                assert [q['game_ids'] for q in job._queue] == [[100]]
            finally:
                self._stop_all(job, alive)
