# =============================================================================
# Pass 38.1 (partial 3/4) — _build_scrape_history_json helper
# =============================================================================
# The "CREATE SCRAPE HISTORY" block inside apply_hybrid_metadata reads
# games.scrape_history (JSON), appends a new entry summarising the current
# scrape, and serialises back to JSON for the save-block UPDATE.  Pass 38.1
# (partial 3/4) extracted this into a helper so the apply_hybrid_metadata
# tail is shorter and the contract is testable in isolation.
# =============================================================================

import json
import os
import sqlite3
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


@pytest.fixture
def cursor(tmp_path):
    """Return a sqlite3 cursor against a 1-row games-style table."""
    db_path = tmp_path / 'test.db'
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE games (
            id INTEGER PRIMARY KEY,
            scrape_history TEXT
        )
    """)
    return conn


class TestBuildScrapeHistoryJson:
    def test_first_scrape_creates_single_entry_history(self, cursor):
        """No prior scrape_history (NULL) — helper starts a fresh list."""
        from scraper import hybrid_scraper

        cursor.execute("INSERT INTO games (id, scrape_history) VALUES (1, NULL)")
        cursor.commit()
        c = cursor.cursor()
        result = {'sources_used': ['IGDB'], 'filled_fields': ['title (IGDB)']}
        metadata = {'title': 'Sonic', 'genre': ''}

        out = hybrid_scraper._build_scrape_history_json(
            c, 1, 'igdb', metadata, result, force_overwrite=False,
        )
        history = json.loads(out)
        assert len(history) == 1
        entry = history[0]
        assert entry['primary_source'] == 'igdb'
        assert entry['sources_used'] == ['IGDB']
        assert entry['fields_filled'] == ['title (IGDB)']
        assert entry['fields_missing'] == ['genre']  # empty metadata key
        assert entry['scrape_mode'] == 'fill_missing'
        assert 'timestamp' in entry  # ISO string, format-loose

    def test_subsequent_scrape_appends_to_existing_history(self, cursor):
        """Existing history JSON is parsed and appended to."""
        from scraper import hybrid_scraper

        prior = [{'timestamp': '2026-04-01T00:00:00', 'primary_source': 'tgdb',
                  'sources_used': ['TGDB'], 'fields_filled': [],
                  'fields_missing': [], 'scrape_mode': 'fill_missing'}]
        cursor.execute(
            "INSERT INTO games (id, scrape_history) VALUES (1, ?)",
            (json.dumps(prior),),
        )
        cursor.commit()
        c = cursor.cursor()
        result = {'sources_used': ['IGDB'], 'filled_fields': []}
        metadata = {'title': 'Sonic'}

        out = hybrid_scraper._build_scrape_history_json(
            c, 1, 'igdb', metadata, result, force_overwrite=False,
        )
        history = json.loads(out)
        assert len(history) == 2
        assert history[0]['primary_source'] == 'tgdb'  # original preserved
        assert history[1]['primary_source'] == 'igdb'

    def test_force_overwrite_records_full_rescrape_mode(self, cursor):
        """`scrape_mode` reflects whether this is a fill or a full re-scrape —
        downstream UI uses this to colour-code the audit trail."""
        from scraper import hybrid_scraper

        cursor.execute("INSERT INTO games (id, scrape_history) VALUES (1, NULL)")
        cursor.commit()
        c = cursor.cursor()
        result = {'sources_used': [], 'filled_fields': []}

        out = hybrid_scraper._build_scrape_history_json(
            c, 1, 'tgdb', {}, result, force_overwrite=True,
        )
        history = json.loads(out)
        assert history[0]['scrape_mode'] == 'full_rescrape'

    def test_corrupted_existing_history_resets_to_fresh_list(self, cursor):
        """If `scrape_history` is unparseable (DB corruption / partial write),
        the helper rolls back to `[]` so the new scrape entry becomes the
        first of a fresh list. Same robustness the inline version had."""
        from scraper import hybrid_scraper

        cursor.execute(
            "INSERT INTO games (id, scrape_history) VALUES (1, ?)",
            ('{not-valid-json',),
        )
        cursor.commit()
        c = cursor.cursor()
        result = {'sources_used': ['IGDB'], 'filled_fields': []}

        out = hybrid_scraper._build_scrape_history_json(
            c, 1, 'igdb', {}, result, force_overwrite=False,
        )
        history = json.loads(out)
        assert len(history) == 1
        assert history[0]['primary_source'] == 'igdb'

    def test_fields_missing_lists_empty_metadata_keys(self, cursor):
        """The `fields_missing` entry is computed from `metadata` — every
        key whose value is falsy is reported missing."""
        from scraper import hybrid_scraper

        cursor.execute("INSERT INTO games (id, scrape_history) VALUES (1, NULL)")
        cursor.commit()
        c = cursor.cursor()
        result = {'sources_used': [], 'filled_fields': []}
        metadata = {
            'title': 'Sonic',  # filled
            'genre': '',        # missing (empty string)
            'year': None,       # missing (None)
            'players': 0,       # missing (zero is falsy)
        }

        out = hybrid_scraper._build_scrape_history_json(
            c, 1, 'igdb', metadata, result, force_overwrite=False,
        )
        history = json.loads(out)
        assert set(history[0]['fields_missing']) == {'genre', 'year', 'players'}
