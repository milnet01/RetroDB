"""PASS-59-125: the bulk scrape job searches with the title derived from the
ROM filename, never the stored title, so a wrong stored title is not
re-confirmed on every re-scrape."""
import sqlite3
from unittest.mock import patch

import pytest

from services.jobs import bulk_scrape as bulk_scrape_mod
from services.jobs.bulk_scrape import BulkScrapeJob


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / 'roms.db'
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT, folder TEXT);
        CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, system_id INTEGER,
                            rom_path TEXT, last_bulk_scraped TEXT);
        INSERT INTO systems VALUES (1, 'Atari 2600', 'atari2600'),
                                   (2, 'ZX Spectrum', 'zxspectrum');
        INSERT INTO games (id, title, system_id, rom_path) VALUES
            (1, 'Adventure', 1,
             '/roms/atari2600/Pitfall! - Pitfall Harry''s Jungle Adventure (USA).zip'),
            (2, 'Auf Wiedersehen Monty', 2,
             '/roms/zxspectrum/Outrun (1987) (U.S. Gold).zip'),
            (3, 'Stored Title Only', 1, NULL);
    """)
    conn.commit()
    conn.close()
    return path


def _connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


@pytest.mark.parametrize('scrape_mode', ['fill_missing', 'full_rescrape'])
def test_bulk_scrape_searches_by_filename_title(db_path, scrape_mode):
    searched = []

    def fake_search(title, system_name, system_folder):
        searched.append(title)
        return []

    job = BulkScrapeJob()
    job.game_ids = [1, 2, 3]
    job.scrape_mode = scrape_mode
    with patch.object(bulk_scrape_mod, '_get_conn', side_effect=lambda: _connect(db_path)), \
         patch.object(bulk_scrape_mod, 'persist_job_start', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_progress', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_complete', return_value=None), \
         patch.object(job, '_finish_worker'), \
         patch('scraper.scraper_manager.load_scraper_settings', return_value={}), \
         patch('scraper.scraper_manager.get_match_settings', return_value={'mode': 'off'}), \
         patch('scraper.scraper_manager.scraper_manager.search_games', side_effect=fake_search):
        job._run_scrape()

    assert searched == [
        "Pitfall!: Pitfall Harry's Jungle Adventure",
        'Outrun',
        'Stored Title Only',  # no ROM file: the stored title is all there is
    ]
