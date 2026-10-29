"""Regression pins for the background-job / installer review fixes.

- RARefreshJob.start() takes the system_name routes/ra_sync.py passes it
  (the per-system refresh raised TypeError before).
- swap_with_running / demote_running drop the promoted job's 'queued'
  job_queue row, as _start_next_queued already did.
- PlayerCoresJob runs a core queued in the window after its worker found
  the queue empty, instead of stranding it.
- MuseumImageFetchJob ends (not stuck `running`) when the DB connect fails.
- install_launcher.exec_arg quotes an Exec path with a space.
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

from services.jobs.bulk_scrape import BulkScrapeJob
from tests._bulk_scrape_fixtures import (
    bulk_scrape_persistence_patches,
    make_memory_db,
)


def test_ra_refresh_start_accepts_system_name():
    from services.jobs import ra_refresh as mod
    job = mod.RARefreshJob()
    with patch.object(mod, 'acquire_job_singleton_lock', return_value=0), \
         patch.object(mod.RARefreshJob, '_run_refresh', lambda self: None):
        result = job.start(system_id=7, system_name='Mega Drive')
        job._thread.join(timeout=2)
    assert result['success']
    assert job.get_status()['system_name'] == 'Mega Drive'


@pytest.mark.parametrize('action', ['swap', 'demote'])
def test_promoted_job_queue_row_removed(action):
    stop = threading.Event()

    def worker(self):
        while not stop.is_set():
            with self._lock:
                if self.cancelled:
                    return
            stop.wait(0.02)

    with bulk_scrape_persistence_patches(make_memory_db()) as mod, \
         patch.object(BulkScrapeJob, '_run_scrape', worker), \
         patch.object(mod, 'remove_queued_job') as remove:
        job = BulkScrapeJob()
        try:
            job.start([100], system_id=1)
            job.start([200], system_id=2)   # queued; persist_job_queued -> 999
            promoted = job._queue[0]['job_id']
            if action == 'swap':
                assert job.swap_with_running(promoted)['success']
            else:
                assert job.demote_running()['success']
            remove.assert_called_once_with(999)
        finally:
            stop.set()
            if job._thread:
                job._thread.join(timeout=2)


def test_player_cores_runs_a_core_queued_after_the_drain():
    from services.jobs import player_cores as mod
    import services.player_cores as pc

    job = mod.PlayerCoresJob()
    job.running = True
    job.job_id = 'player_cores_test'
    job.app = MagicMock()
    real_next = mod.PlayerCoresJob._next
    calls = {'n': 0}

    def racing_next(self):
        calls['n'] += 1
        if calls['n'] == 1:
            # request() lands just after the worker saw an empty queue.
            with self._lock:
                self.queue.append(('late_core', None, False))
            return None
        return real_next(self)

    with patch.object(mod, 'acquire_job_singleton_lock', return_value=0), \
         patch.object(mod.PlayerCoresJob, '_next', racing_next), \
         patch.object(pc, 'is_installed', return_value=True):
        job._worker()
        if job._thread:
            job._thread.join(timeout=5)

    status = job.get_status()
    assert 'late_core' in status['success']
    assert status['running'] is False
    assert status['queued'] == []


def test_museum_images_job_ends_when_connect_fails():
    from services.jobs import museum_images as mod
    job = mod.MuseumImageFetchJob()
    job.running = True
    with patch.object(mod, '_get_conn', side_effect=RuntimeError('db gone')):
        job._worker(1)
    status = job.get_status()
    assert status['running'] is False
    assert status['completed'] is True
    assert 'db gone' in status['error']


def test_install_launcher_quotes_exec_paths():
    from scripts.install_launcher import exec_arg
    assert exec_arg('/usr/bin/python3') == '/usr/bin/python3'
    assert exec_arg('/home/u/My Games/app.py') == '"/home/u/My Games/app.py"'
    assert exec_arg('/a b/$x') == '"/a b/\\\\$x"'
    assert exec_arg('/a/50%') == '/a/50%%'


def test_recoverable_multi_system_scrapes_are_not_collapsed(tmp_path):
    import json
    import sqlite3
    from services.jobs import base as base_mod

    db = tmp_path / 'jobs.db'
    conn = sqlite3.connect(db)
    conn.executescript("""
        CREATE TABLE job_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT, job_type TEXT NOT NULL,
            status TEXT, progress TEXT, created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, completed_at TEXT, error_message TEXT,
            params TEXT);
    """)
    rows = [
        ({'system_id': None, 'game_ids': [1, 2]}, 1),   # two different selections
        ({'system_id': None, 'game_ids': [3, 4]}, 0),
        ({'system_id': 5, 'game_ids': [6]}, 0),          # same-system duplicates
        ({'system_id': 5, 'game_ids': [6]}, 1),
    ]
    for i, (params, current) in enumerate(rows):
        conn.execute(
            "INSERT INTO job_queue (job_type, status, progress, created_at, updated_at, params) "
            "VALUES ('bulk_scrape', 'interrupted', ?, ?, ?, ?)",
            (json.dumps({'current': current}), f'2026-01-0{i + 1}', f'2026-01-0{i + 1}',
             json.dumps(params)))
    conn.commit()
    conn.close()

    def _conn():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    with patch.object(base_mod, '_get_conn', _conn):
        jobs = base_mod.get_recoverable_jobs()

    kept = sorted(tuple(j['params']['game_ids']) for j in jobs)
    assert kept == [(1, 2), (3, 4), (6,)]
