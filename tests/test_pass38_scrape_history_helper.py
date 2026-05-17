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
import re
import sqlite3
from datetime import datetime, timedelta

import pytest

from tests._util import REPO_ROOT  # noqa: F401  (ensures sys.path is set)


@pytest.fixture
def connection(tmp_path):
    """Return a sqlite3 Connection against a 1-row games-style table.

    Test bodies obtain a cursor via ``connection.cursor()`` — the fixture
    name was previously ``cursor`` but it returned the Connection, which
    was a Pass-c-006 N-1 finding.

    Yields with explicit close in teardown — CPython's refcount closes
    promptly today, but PyPy / pytest-xdist process reuse can hold the
    WAL lock past test boundaries without the explicit close."""
    db_path = tmp_path / 'test.db'
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE games (
            id INTEGER PRIMARY KEY,
            scrape_history TEXT
        )
    """)
    try:
        yield conn
    finally:
        conn.close()


class TestBuildScrapeHistoryJson:
    def test_first_scrape_creates_single_entry_history(self, connection):
        """No prior scrape_history (NULL) — helper starts a fresh list."""
        from scraper import hybrid_scraper

        connection.execute("INSERT INTO games (id, scrape_history) VALUES (1, NULL)")
        connection.commit()
        c = connection.cursor()
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
        # ISO-8601 prefix (YYYY-MM-DDTHH:MM:SS); avoids the c-006 D-1 finding
        # where "key present" was the only check and any junk value passed.
        assert isinstance(entry['timestamp'], str)
        assert re.match(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}', entry['timestamp']), (
            f"timestamp must be ISO-8601, got {entry['timestamp']!r}"
        )
        # c-005 LOW fix: recency check — format-only pin would pass for a
        # hardcoded epoch string like "2000-01-01T00:00:00". Assert the
        # timestamp is within the last 5 seconds (the helper writes
        # datetime.now() so a fresh write must satisfy this).
        assert datetime.fromisoformat(entry['timestamp']) > (
            datetime.now() - timedelta(seconds=5)
        ), (
            f"timestamp must be fresh, got {entry['timestamp']!r} "
            "(more than 5 s in the past suggests a hardcoded value)"
        )

    def test_subsequent_scrape_appends_to_existing_history(self, connection):
        """Existing history JSON is parsed and appended to."""
        from scraper import hybrid_scraper

        prior = [{'timestamp': '2026-04-01T00:00:00', 'primary_source': 'tgdb',
                  'sources_used': ['TGDB'], 'fields_filled': [],
                  'fields_missing': [], 'scrape_mode': 'fill_missing'}]
        connection.execute(
            "INSERT INTO games (id, scrape_history) VALUES (1, ?)",
            (json.dumps(prior),),
        )
        connection.commit()
        c = connection.cursor()
        result = {'sources_used': ['IGDB'], 'filled_fields': []}
        metadata = {'title': 'Sonic'}

        out = hybrid_scraper._build_scrape_history_json(
            c, 1, 'igdb', metadata, result, force_overwrite=False,
        )
        history = json.loads(out)
        assert len(history) == 2
        assert history[0]['primary_source'] == 'tgdb'  # original preserved
        assert history[1]['primary_source'] == 'igdb'

    def test_force_overwrite_records_full_rescrape_mode(self, connection):
        """`scrape_mode` reflects whether this is a fill or a full re-scrape —
        downstream UI uses this to colour-code the audit trail."""
        from scraper import hybrid_scraper

        connection.execute("INSERT INTO games (id, scrape_history) VALUES (1, NULL)")
        connection.commit()
        c = connection.cursor()
        result = {'sources_used': [], 'filled_fields': []}

        out = hybrid_scraper._build_scrape_history_json(
            c, 1, 'tgdb', {}, result, force_overwrite=True,
        )
        history = json.loads(out)
        assert history[0]['scrape_mode'] == 'full_rescrape'

    def test_corrupted_existing_history_resets_to_fresh_list(self, connection):
        """If `scrape_history` is unparseable (DB corruption / partial write),
        the helper rolls back to `[]` so the new scrape entry becomes the
        first of a fresh list. Same robustness the inline version had."""
        from scraper import hybrid_scraper

        connection.execute(
            "INSERT INTO games (id, scrape_history) VALUES (1, ?)",
            ('{not-valid-json',),
        )
        connection.commit()
        c = connection.cursor()
        result = {'sources_used': ['IGDB'], 'filled_fields': []}

        out = hybrid_scraper._build_scrape_history_json(
            c, 1, 'igdb', {}, result, force_overwrite=False,
        )
        history = json.loads(out)
        assert len(history) == 1
        assert history[0]['primary_source'] == 'igdb'

    def test_fields_missing_lists_empty_metadata_keys(self, connection):
        """The `fields_missing` entry is computed from `metadata` — every
        key whose value is falsy is reported missing."""
        from scraper import hybrid_scraper

        connection.execute("INSERT INTO games (id, scrape_history) VALUES (1, NULL)")
        connection.commit()
        c = connection.cursor()
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
