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


# --- C. Process lifecycle -----------------------------------------------------------

def test_cancelling_core_downloads_stops_after_the_current_one():
    from services.jobs.player_cores import PlayerCoresJob
    job = PlayerCoresJob()
    job.running = True
    job.queue = [('snes9x', 1, False), ('mgba', 2, False)]
    job.cancel()
    assert job._next() is None
    assert job.queue == []


def test_importing_app_does_not_touch_a_live_servers_jobs(tmp_path):
    """Only the serving process marks jobs interrupted; `import app` from a
    script or a second process used to flag the live server's jobs."""
    import os
    import subprocess
    import sys
    from services import migrations
    from tests._util import REPO_ROOT
    db = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(db)
    migrations.apply_pending(conn)
    conn.execute("INSERT INTO job_queue (job_type, status, created_at, updated_at) "
                 "VALUES ('bulk_scrape', 'running', 'x', 'x')")
    conn.execute("INSERT INTO wishlist (title, scrape_status) VALUES ('Live', 'scraping')")
    conn.commit()
    conn.close()
    env = {**os.environ, 'RETRODB_DB_PATH': db}
    res = subprocess.run([sys.executable, '-c', 'import app'], cwd=REPO_ROOT, env=env,
                         capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr[-800:]
    conn = sqlite3.connect(db)
    assert conn.execute("SELECT status FROM job_queue").fetchone()[0] == 'running'
    assert conn.execute("SELECT scrape_status FROM wishlist").fetchone()[0] == 'scraping'
    conn.close()


def test_a_restart_frees_wishlist_items_left_scraping(tmp_path, monkeypatch):
    import config
    from services import migrations, wishlist_scraper
    db = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(db)
    migrations.apply_pending(conn)
    conn.execute("INSERT INTO wishlist (title, scrape_status) VALUES ('Stuck', 'scraping')")
    conn.commit()
    monkeypatch.setattr(config, 'DB_PATH', db)
    assert wishlist_scraper.free_stuck_scrapes() == 1
    assert conn.execute("SELECT scrape_status FROM wishlist").fetchone()[0] == 'unscraped'
    conn.close()


def test_a_wishlist_item_that_raises_in_scrape_all_is_marked_failed(monkeypatch):
    from services import wishlist_scraper
    statuses = []
    monkeypatch.setattr(wishlist_scraper, 'query', lambda *a, **k: [{'id': 7}])
    monkeypatch.setattr(wishlist_scraper, '_set_status', lambda i, s: statuses.append((i, s)))

    def boom(item_id):
        statuses.append((item_id, 'scraping'))
        raise RuntimeError('source fell over')
    monkeypatch.setattr(wishlist_scraper, 'scrape_wishlist_item', boom)
    wishlist_scraper.scrape_unscraped_items()
    assert statuses[-1] == (7, 'failed')


def test_only_one_wishlist_scrape_all_runs_at_once(monkeypatch):
    from services import wishlist_scraper
    gate, calls = threading.Event(), []
    monkeypatch.setattr(wishlist_scraper, 'scrape_unscraped_items',
                        lambda owner_id=None: calls.append(owner_id) or gate.wait(5))
    first = wishlist_scraper.scrape_unscraped_items_async(1)
    second = wishlist_scraper.scrape_unscraped_items_async(1)
    gate.set()
    first.join(5)
    if second is not None:
        second.join(5)
    assert calls == [1]


def test_two_people_can_each_scrape_their_own_wishlist(monkeypatch):
    from services import wishlist_scraper
    gate, calls = threading.Event(), []
    monkeypatch.setattr(wishlist_scraper, 'scrape_unscraped_items',
                        lambda owner_id=None: calls.append(owner_id) or gate.wait(5))
    threads = [wishlist_scraper.scrape_unscraped_items_async(o) for o in (1, 2, None)]
    gate.set()
    for t in threads:
        if t is not None:
            t.join(5)
    assert sorted(calls) == [1, 2] and threads[2] is None


def test_a_second_starting_process_does_not_rerun_migrations(tmp_path, monkeypatch):
    """apply_pending read user_version before its lock; a process that read
    it while another migrated re-ran every migration and set it back."""
    from services import migrations
    conn = sqlite3.connect(str(tmp_path / 'roms.db'))
    migrations.apply_pending(conn)
    latest = migrations.latest_version()
    monkeypatch.setattr(migrations, 'current_version', lambda c: 0)  # its stale read
    assert migrations.apply_pending(conn) == []
    assert conn.execute("PRAGMA user_version").fetchone()[0] == latest
    conn.close()
