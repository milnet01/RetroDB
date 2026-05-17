"""State-machine tests for BulkScrapeJob (Pass 14.3b).

Pins the transitions that the UI relies on:
    idle -> start -> running
    running -> pause -> paused
    paused -> resume -> running
    running -> cancel -> cancelled (loop exits)
    start while running -> queue (with duplicate rejection)
    cancel_queued / cancel_all_queued / promote_queued / demote_queued

The real `_run_scrape()` is a network-heavy loop; here it's stubbed to a no-op
so the state machine can be exercised without spawning scrapers.
"""

import sqlite3
from unittest.mock import patch

import pytest

from services.jobs import bulk_scrape as bulk_scrape_mod
from services.jobs.bulk_scrape import BulkScrapeJob


def _make_memory_db():
    """Build a minimal in-memory DB the job's `start()` can query for system/game titles."""
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, system_id INTEGER);
        INSERT INTO systems (id, name) VALUES (1, 'NES'), (2, 'SNES');
        INSERT INTO games (id, title, system_id) VALUES
            (100, 'Super Mario Bros', 1),
            (101, 'Zelda', 1),
            (200, 'F-Zero', 2);
    """)
    return conn


@pytest.fixture
def job():
    """Fresh BulkScrapeJob with all DB I/O and the background thread stubbed out.

    Yields the job; on teardown, forces running/completed flags so anything
    the state machine might have started settles instead of leaking threads.
    """
    mem_db = _make_memory_db()

    # Patch persistence + connection helpers + the thread target so start()
    # never talks to the real DB or spawns a real scraper.
    #
    # v3.6.7 — also patch `acquire_job_singleton_lock` to return the
    # sentinel `0` ("acquired, no real lock"). Without this, `start()`
    # calls fcntl.flock against the shared on-disk file
    # `<DB_DIR>/job_locks/bulk_scrape.lock`, and if a live RetroDB server
    # is running on this machine and currently holds that lock (e.g. the
    # user's local dev server with an interrupted job), every test that
    # invokes `start()` returns `success=False` with "already running on
    # another worker". The sentinel `0` is later passed to
    # `release_job_singleton_lock(0)` which is a documented no-op.
    with patch.object(bulk_scrape_mod, '_get_conn', return_value=mem_db), \
         patch.object(bulk_scrape_mod, 'persist_job_start', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_progress', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_complete', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_queued', return_value=999), \
         patch.object(bulk_scrape_mod, 'remove_queued_job', return_value=None), \
         patch.object(bulk_scrape_mod, 'acquire_job_singleton_lock', return_value=0), \
         patch.object(BulkScrapeJob, '_run_scrape', lambda self: None):
        j = BulkScrapeJob()
        yield j
        # Forcibly mark completed so any lingering logic sees a terminal state.
        with j._lock:
            j.running = False
            j.completed = True
        # Pass 41.6.A — release the singleton FD if start() acquired one
        # in this test. The patched `_run_scrape` is a no-op, so
        # `_start_next_queued`'s normal release path never fires; without
        # this teardown the file lock survives the test and the next
        # test's start() returns "already running on another worker".
        from services.jobs.base import release_job_singleton_lock
        if getattr(j, '_singleton_fd', None) is not None:
            release_job_singleton_lock(j._singleton_fd)
            j._singleton_fd = None


class TestInitialState:
    def test_freshly_constructed_job_is_idle(self, job):
        assert job.running is False
        assert job.paused is False
        assert job.cancelled is False
        assert job.completed is False
        assert job.job_id is None
        assert job.game_ids == []
        assert job.success_count == 0
        assert job.failed_count == 0
        assert job.skipped_count == 0

    def test_pause_when_idle_fails(self, job):
        assert job.pause() == {'success': False, 'error': 'No running job to pause'}

    def test_resume_when_idle_fails(self, job):
        assert job.resume() == {'success': False, 'error': 'No paused job to resume'}

    def test_cancel_when_idle_fails(self, job):
        assert job.cancel() == {'success': False, 'error': 'No running job to cancel'}


class TestStart:
    def test_first_start_runs_immediately(self, job):
        result = job.start([100, 101], system_id=1)
        assert result['success'] is True
        assert result['queued'] is False
        assert result['total'] == 2
        assert result['system_name'] == 'NES'
        # Thread was started (stubbed target, so no-op), but state machine advanced.
        assert job.running is True
        assert job.job_id is not None
        assert job.system_id == 1

    def test_second_start_queues(self, job):
        job.start([100], system_id=1)
        result = job.start([200], system_id=2)
        assert result['success'] is True
        assert result['queued'] is True
        assert result['queue_position'] == 1
        assert len(job._queue) == 1
        assert job._queue[0]['system_id'] == 2

    def test_duplicate_system_and_mode_rejected_when_running(self, job):
        job.start([100], system_id=1, scrape_mode='fill_missing')
        result = job.start([101], system_id=1, scrape_mode='fill_missing')
        assert result['success'] is False
        assert 'already running' in result['error']

    def test_duplicate_system_and_mode_rejected_when_queued(self, job):
        job.start([100], system_id=1)
        job.start([200], system_id=2)
        # Now another request for system_id=2 with same mode should be rejected.
        result = job.start([200], system_id=2)
        assert result['success'] is False
        assert 'already queued' in result['error']

    def test_different_mode_for_same_system_is_not_duplicate(self, job):
        job.start([100], system_id=1, scrape_mode='fill_missing')
        result = job.start([100], system_id=1, scrape_mode='full_rescrape')
        assert result['success'] is True
        assert result['queued'] is True

    def test_start_with_empty_game_ids(self, job):
        """COV-2: `start([], system_id=…)` is currently a valid call path
        (nothing in bulk_scrape.py guards against it). Pin today's
        contract — succeeds with total=0 — so any future change that
        rejects empty lists at this layer fails this test and forces a
        review of the call-sites in `routes/bulk_scrape.py`."""
        result = job.start([], system_id=1)
        assert result['success'] is True
        assert result['queued'] is False
        assert result['total'] == 0
        assert job.game_ids == []


class TestPauseResume:
    def test_pause_while_running(self, job):
        job.start([100])
        result = job.pause()
        assert result == {'success': True}
        assert job.paused is True
        assert job.running is True  # still running, just paused

    def test_pause_when_already_paused_still_succeeds(self, job):
        job.start([100])
        job.pause()
        # Pausing again isn't treated as an error — the flag is already set.
        result = job.pause()
        assert result == {'success': True}

    def test_resume_when_not_paused_fails(self, job):
        job.start([100])
        result = job.resume()
        assert result == {'success': False, 'error': 'No paused job to resume'}

    def test_pause_then_resume_round_trip(self, job):
        job.start([100])
        job.pause()
        assert job.paused is True
        result = job.resume()
        assert result == {'success': True}
        assert job.paused is False


class TestCancel:
    def test_cancel_while_running(self, job):
        job.start([100])
        result = job.cancel()
        assert result == {'success': True}
        assert job.cancelled is True
        # Cancel must clear paused flag so the _run_scrape loop can observe cancellation.
        assert job.paused is False

    def test_cancel_while_paused_unpauses_and_cancels(self, job):
        job.start([100])
        job.pause()
        job.cancel()
        assert job.cancelled is True
        assert job.paused is False


class TestQueueManagement:
    def _fill_queue(self, job, n=3):
        """Start 1 running job + n queued jobs on distinct systems."""
        job.start([100], system_id=1)
        queued_ids = []
        for i in range(n):
            sys_id = 10 + i
            # The queued job doesn't actually look up its system name beyond the
            # real DB — the test stubbed DB has only systems 1,2 but that's fine
            # because `_get_system_name` just returns 'Unknown System' which is OK.
            r = job.start([200 + i], system_id=sys_id)
            queued_ids.append(r['job_id'])
        return queued_ids

    def test_cancel_queued_removes_that_entry(self, job):
        ids = self._fill_queue(job, 3)
        result = job.cancel_queued(ids[1])
        assert result == {'success': True}
        assert len(job._queue) == 2
        remaining = {q['job_id'] for q in job._queue}
        assert ids[1] not in remaining

    def test_cancel_queued_unknown_id_fails(self, job):
        self._fill_queue(job, 2)
        result = job.cancel_queued('nonexistent_job')
        assert result == {'success': False, 'error': 'Queued job not found'}

    def test_cancel_all_queued_empties_queue(self, job):
        self._fill_queue(job, 3)
        result = job.cancel_all_queued()
        assert result == {'success': True, 'cancelled_count': 3}
        assert job._queue == []

    def test_promote_queued_moves_up_one_slot(self, job):
        ids = self._fill_queue(job, 3)
        # Move ids[2] from position 2 to position 1.
        result = job.promote_queued(ids[2])
        assert result == {'success': True}
        assert [q['job_id'] for q in job._queue] == [ids[0], ids[2], ids[1]]

    def test_promote_front_of_queue_is_noop(self, job):
        ids = self._fill_queue(job, 2)
        result = job.promote_queued(ids[0])
        assert result['success'] is True
        assert result.get('message') == 'Already next in queue'
        assert [q['job_id'] for q in job._queue] == ids

    def test_demote_queued_moves_down_one_slot(self, job):
        ids = self._fill_queue(job, 3)
        result = job.demote_queued(ids[0])
        assert result == {'success': True}
        assert [q['job_id'] for q in job._queue] == [ids[1], ids[0], ids[2]]

    def test_demote_back_of_queue_is_noop(self, job):
        ids = self._fill_queue(job, 2)
        result = job.demote_queued(ids[-1])
        assert result['success'] is True
        assert result.get('message') == 'Already last in queue'
        assert [q['job_id'] for q in job._queue] == ids


class TestGetStatus:
    def test_status_on_idle_job(self, job):
        status = job.get_status()
        assert status['running'] is False
        assert status['completed'] is False

    def test_status_while_running(self, job):
        job.start([100, 101], system_id=1)
        status = job.get_status()
        assert status['running'] is True
        assert status['total'] == 2
        assert status['system_name'] == 'NES'
