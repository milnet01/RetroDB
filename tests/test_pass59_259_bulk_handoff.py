"""PASS-59-259: a bulk scrape worker another job has replaced does not count
its game in flight into the new job, and each worker carries its own job."""
import threading
from unittest.mock import patch

from services.jobs import bulk_scrape as bulk_scrape_mod
from services.jobs.bulk_scrape import BulkScrapeJob
from tests.test_bulk_scrape_search_title import _connect, db_path  # noqa: F401  (fixture)


def _run(job, db_path, search):
    with patch.object(bulk_scrape_mod, '_get_conn', side_effect=lambda: _connect(db_path)), \
         patch.object(bulk_scrape_mod, 'persist_job_start', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_progress', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_complete', return_value=None), \
         patch.object(job, '_finish_worker'), \
         patch.object(job, '_stamp_bulk_scraped'), \
         patch('scraper.scraper_manager.load_scraper_settings', return_value={}), \
         patch('scraper.scraper_manager.get_match_settings', return_value={'mode': 'off'}), \
         patch('scraper.scraper_manager.scraper_manager.search_games', side_effect=search):
        job._run_scrape()


def test_a_replaced_worker_does_not_count_its_game_in_flight(db_path):
    job = BulkScrapeJob()
    job.game_ids = [1]
    job.scrape_mode = 'full_rescrape'

    def swap_during_the_search(title, system_name, system_folder):
        with job._lock:              # a swap that gave up waiting for this worker
            job.reset()
            job.job_id, job.running = 'new', True
        return []                    # then the old worker's game finds nothing
    _run(job, db_path, swap_during_the_search)
    assert (job.success_count, job.failed_count, job.skipped_count) == (0, 0, 0)


def test_a_worker_counts_its_own_games(db_path):
    job = BulkScrapeJob()
    job.game_ids = [1]
    job.scrape_mode = 'full_rescrape'
    _run(job, db_path, lambda *a: [])
    assert job.failed_count == 1


def test_a_worker_runs_the_job_it_was_started_for():
    """A swap made between start and the thread's first line used to hand the
    old thread the new job's token, so it ran as if it were current."""
    seen = []
    job = BulkScrapeJob()
    job.game_ids, job.scrape_mode, job.job_id = [7], 'fill_missing', 'first'
    gate = threading.Event()

    def worker(self):
        gate.wait(5)
        seen.append(threading.current_thread().scrape_job)
    with patch.object(BulkScrapeJob, '_run_scrape', worker):
        job._start_worker()
        with job._lock:
            job.reset()
            job.game_ids, job.job_id = [8], 'second'
        gate.set()
        job._thread.join(5)
    assert seen == [(job._run_token - 1, [7], 'fill_missing', 'first')]
