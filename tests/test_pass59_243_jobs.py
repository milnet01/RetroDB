"""PASS-59-243: background jobs survive one bad game."""
import sqlite3

from tests.test_ai_fill_bulk import _game, _run, db  # noqa: F401  (db is a fixture)
from tests.test_pass59_202_ss_regions import ROM, _run_job, library  # noqa: F401


def test_one_game_raising_does_not_end_the_ai_fill_run(db, monkeypatch):  # noqa: F811
    for title in ('A', 'B', 'C'):
        _game(db, title)

    def answer(title):
        if title == 'B':
            raise RuntimeError('provider fell over')
        return {'units_sold': '5000'}
    status = _run(monkeypatch, db.sids[0], answer)
    assert (status['success'], status['failed'], status['error']) == (2, 1, None)


def test_one_game_raising_does_not_end_the_region_repair(library, monkeypatch):  # noqa: F811
    import config
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("INSERT INTO games (id, system_id, title, rom_path, screenscraper_id, boxart) "
                 "VALUES (2, 1, 'Sonic 2', ?, 78, '2_ss_boxart.webp')",
                 (ROM.replace('Sonic', 'Sonic 2'),))
    conn.commit()
    conn.close()
    from services.jobs import ss_region_repair as mod
    seen = []

    def search(title, folder, *a, **k):
        seen.append(title)
        if title == 'Sonic':
            raise ConnectionError('network down')
        return None
    monkeypatch.setattr(mod, 'search_game', search)
    job = mod.SsRegionRepairJob()
    job.running = True
    job._worker({'screenscraper_username': 'u', 'screenscraper_password': 'p'})
    assert sorted(seen) == ['Sonic', 'Sonic 2']
    assert job.error_message is None
    assert job.failed_count == 1


# --- B. The bulk-scrape queue ----------------------------------------------------

import threading  # noqa: E402
from unittest.mock import patch  # noqa: E402

import pytest  # noqa: E402

from services.jobs.bulk_scrape import BulkScrapeJob  # noqa: E402
from tests._bulk_scrape_fixtures import (  # noqa: E402
    bulk_scrape_persistence_patches, make_memory_db,
)


@pytest.fixture
def bulk():
    jobs = []
    with bulk_scrape_persistence_patches(make_memory_db()) as mod:
        yield mod, jobs
    from services.jobs.base import release_job_singleton_lock
    for job in jobs:
        if getattr(job, '_singleton_fd', None) is not None:
            release_job_singleton_lock(job._singleton_fd)


def test_a_replaced_worker_leaves_the_new_job_alone(bulk):
    """After the swap's 60 s wait the old worker kept going beside the new
    one, and its end marked the new job completed."""
    _mod, jobs = bulk
    job = BulkScrapeJob()
    jobs.append(job)
    with patch('scraper.scraper_manager.load_scraper_settings', return_value={'enabled': {}}), \
         patch('scraper.scraper_manager.get_match_settings', return_value={}):
        job.game_ids = [None, None, None]
        job.running, job.paused = True, True
        old = threading.Thread(target=job._run_scrape, daemon=True)
        old.start()
        threading.Event().wait(0.3)          # the old worker waits in its pause
        with job._lock:                      # a swap that gave up waiting
            job.reset()
            job.job_id, job.running = 'new', True
        old.join(5)
    assert not old.is_alive()
    assert (job.job_id, job.running, job.completed) == ('new', True, False)


def _exiting_worker(job):
    while True:
        with job._lock:
            if job.cancelled:
                return
        threading.Event().wait(0.02)


@pytest.mark.parametrize('action', ['swap', 'demote'])
def test_a_displaced_scrape_is_saved_for_after_a_restart(bulk, action):
    mod, jobs = bulk
    with patch.object(BulkScrapeJob, '_run_scrape', _exiting_worker):
        job = BulkScrapeJob()
        jobs.append(job)
        job.start([100, 101], system_id=1)
        job.start([200], system_id=2)
        mod.persist_job_queued.reset_mock()
        with job._lock:
            job.current_index = 1
        promoted = job._queue[0]['job_id']
        try:
            if action == 'swap':
                assert job.swap_with_running(promoted)['success']
            else:
                assert job.demote_running()['success']
            assert job._queue[0]['db_queue_id'] == 999
            (_type, params), kwargs = mod.persist_job_queued.call_args
            assert params['game_ids'] == [None, 101]
            assert kwargs['progress']['current'] == 1
        finally:
            with job._lock:
                job._queue.clear()
                job.cancelled = True


def test_a_resume_queued_behind_a_running_scrape_is_saved(bulk):
    mod, jobs = bulk
    with patch.object(BulkScrapeJob, '_run_scrape', _exiting_worker):
        job = BulkScrapeJob()
        jobs.append(job)
        job.start([100], system_id=1)
        mod.persist_job_queued.reset_mock()
        try:
            assert job.resume_from_params({'game_ids': [200, 101], 'system_id': 2},
                                          progress={'current': 1, 'success': 1})
            assert job._queue[0]['db_queue_id'] == 999
            (_type, params), kwargs = mod.persist_job_queued.call_args
            assert params['game_ids'] == [None, 101]
            assert kwargs['progress']['current'] == 1
        finally:
            with job._lock:
                job._queue.clear()
                job.cancelled = True


def test_a_second_resume_click_is_refused(admin_test_client, monkeypatch):
    import os
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    job_id = conn.execute(
        "INSERT INTO job_queue (job_type, status, params, progress, created_at, updated_at) "
        "VALUES ('ai_fill_bulk', 'interrupted', '{}', '{}', 'x', 'x')").lastrowid
    conn.commit()
    started = []
    from services.jobs import ai_fill_bulk_job
    monkeypatch.setattr(ai_fill_bulk_job, 'resume_from_params',
                        lambda params, progress=None: started.append(1) or True)
    client, csrf = admin_test_client()
    first = client.post(f'/api/jobs/resume/{job_id}', headers={'X-CSRF-Token': csrf})
    second = client.post(f'/api/jobs/resume/{job_id}', headers={'X-CSRF-Token': csrf})
    conn.execute("DELETE FROM job_queue WHERE id = ?", (job_id,))
    conn.commit()
    conn.close()
    assert first.status_code == 200 and second.status_code == 404
    assert started == [1]


def test_resume_claims_the_row_before_starting(monkeypatch):
    """Two clicks that both pass the lookup: only one may start the job."""
    from services.jobs import base
    import os
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    job_id = conn.execute("INSERT INTO job_queue (job_type, status, created_at, updated_at) "
                          "VALUES ('ai_fill_bulk', 'interrupted', 'x', 'x')").lastrowid
    conn.commit()
    try:
        assert base.claim_recoverable_job(job_id) is True
        assert base.claim_recoverable_job(job_id) is False
        base.release_recoverable_job(job_id)
        assert base.claim_recoverable_job(job_id) is True
    finally:
        conn.execute("DELETE FROM job_queue WHERE id = ?", (job_id,))
        conn.commit()
        conn.close()
