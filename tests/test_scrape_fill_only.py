"""Regression tests for Pass 30.4 — IGDB and TGDB `apply_metadata_to_game`
must use COALESCE so that an empty field in the API response never
overwrites a previously-scraped or curated value.

Before Pass 30.4 these scrapers wrote bare `?` for publisher, developer,
release_date, genre, rating, players, modes, description, and boxart —
an empty IGDB/TGDB response would wipe those fields when the source ran
as primary.
"""

import sqlite3

import pytest

from scraper import scrape_igdb, scrape_thegamesdb


class _PersistentConn:
    """Thin wrapper around sqlite3.Connection that ignores .close() so the
    scraper's `finally: conn.close()` doesn't discard the test's connection
    before we assert on it.

    The wrapped connection is closed when the wrapper itself is collected.
    For deterministic close (e.g. on Windows or PyPy where GC is lazier), call
    .real_close() explicitly."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        pass

    def real_close(self):
        """Actually close the underlying connection — used in test teardown."""
        try:
            self._conn.close()
        except Exception:
            pass

    def __del__(self):
        # Best-effort: ensure the in-memory DB is released even if a test
        # forgets to call real_close (c-005 deferred #8 partial fix).
        try:
            self._conn.close()
        except Exception:
            pass


def _make_conn_with_existing_row(**values):
    """Create an in-memory SQLite DB with a `games` row populated from values."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE games (
            id INTEGER PRIMARY KEY,
            title TEXT, publisher TEXT, developer TEXT, release_date TEXT,
            genre TEXT, rating TEXT, esrb_rating TEXT, pegi_rating TEXT,
            players INTEGER, modes TEXT, description TEXT, boxart TEXT,
            screenshots TEXT, fanart TEXT,
            critic_score REAL, critic_score_count INTEGER,
            user_score REAL, user_score_count INTEGER,
            scraped INTEGER DEFAULT 0
        )
    """)
    cols = ', '.join(values.keys())
    placeholders = ', '.join(['?'] * len(values))
    conn.execute(
        f"INSERT INTO games ({cols}) VALUES ({placeholders})",
        tuple(values.values()),
    )
    conn.commit()
    return _PersistentConn(conn)


@pytest.fixture
def noop_download(monkeypatch):
    """Neutralise image-download helpers so tests don't touch the network."""
    monkeypatch.setattr(scrape_igdb, 'download_image', lambda *a, **kw: None)
    monkeypatch.setattr(scrape_thegamesdb, '_download_tgdb_image', lambda *a, **kw: None, raising=False)


def test_igdb_apply_preserves_existing_values_when_response_is_empty(monkeypatch, noop_download):
    conn = _make_conn_with_existing_row(
        id=1, title='Chrono Trigger', publisher='Squaresoft',
        developer='Square', release_date='1995-03-11', genre='RPG',
        rating='92', esrb_rating='T', pegi_rating='12',
        players=1, modes='Single-player',
        description='Time-travel JRPG classic.',
        boxart='static/images/boxart/1.jpg',
    )
    monkeypatch.setattr(scrape_igdb, 'get_scraper_conn', lambda: conn)

    # IGDB returns no usable data (title-only response)
    result = scrape_igdb.apply_metadata_to_game(1, {'name': 'Chrono Trigger'})
    assert result is True

    row = conn.execute("SELECT * FROM games WHERE id=1").fetchone()
    assert row['publisher'] == 'Squaresoft'
    assert row['developer'] == 'Square'
    assert row['release_date'] == '1995-03-11'
    assert row['genre'] == 'RPG'
    assert row['rating'] == '92'
    assert row['esrb_rating'] == 'T'
    assert row['pegi_rating'] == '12'
    assert row['players'] == 1
    assert row['modes'] == 'Single-player'
    assert row['description'] == 'Time-travel JRPG classic.'
    assert row['boxart'] == 'static/images/boxart/1.jpg'


def test_tgdb_apply_preserves_existing_values_when_response_is_empty(monkeypatch, noop_download):
    conn = _make_conn_with_existing_row(
        id=1, title='Mega Man X', publisher='Capcom',
        developer='Capcom', release_date='1993-12-17', genre='Platformer',
        rating='88', esrb_rating='E', pegi_rating='7',
        players=1, modes='Single-player',
        description='SNES action platformer.',
        boxart='static/images/boxart/1.jpg',
    )
    monkeypatch.setattr(scrape_thegamesdb, 'get_scraper_conn', lambda: conn)

    # TGDB returns mostly-empty shape (no publisher, developer, genre, etc.)
    empty_tgdb = {
        'game_title': 'Mega Man X',
        'publishers': [],
        'developers': [],
        'release_date': '',
        'genres': [],
        'rating': '',
        'players': 0,
        'overview': '',
        'boxart': '',
        'screenshots': [],
        'fanart': '',
    }
    result = scrape_thegamesdb.apply_metadata_to_game(1, empty_tgdb)
    assert result is True

    row = conn.execute("SELECT * FROM games WHERE id=1").fetchone()
    assert row['publisher'] == 'Capcom'
    assert row['developer'] == 'Capcom'
    assert row['release_date'] == '1993-12-17'
    assert row['genre'] == 'Platformer'
    assert row['rating'] == '88'
    assert row['esrb_rating'] == 'E'
    assert row['pegi_rating'] == '7'
    assert row['players'] == 1
    assert row['modes'] == 'Single-player'
    assert row['description'] == 'SNES action platformer.'
    assert row['boxart'] == 'static/images/boxart/1.jpg'


# -----------------------------------------------------------------------------
# Failure-path coverage (test-audit c-007 LOW-3)
# -----------------------------------------------------------------------------
#
# The above tests pin the happy path. These pin the failure path: when the
# scraper hits a DB error (e.g. connection dies mid-UPDATE), `apply_metadata_
# to_game` must catch it and return False rather than re-raising. A silent
# True on failure would let downstream callers assume the row was updated.

class _FailingConn:
    """Connection that raises on .cursor() so the scraper enters its except branch."""

    def cursor(self):
        raise sqlite3.OperationalError("simulated DB failure")

    def rollback(self):
        pass

    def close(self):
        pass


def test_igdb_apply_returns_false_when_db_fails(monkeypatch, noop_download):
    """A DB error inside `apply_metadata_to_game` must surface as False
    (not a silent True, not a re-raise). Pins the COALESCE invariant's
    failure-side contract."""
    monkeypatch.setattr(scrape_igdb, 'get_scraper_conn', lambda: _FailingConn())
    result = scrape_igdb.apply_metadata_to_game(999, {'name': 'No Such Game'})
    assert result is False


def test_tgdb_apply_returns_false_when_db_fails(monkeypatch, noop_download):
    """Mirror of the IGDB failure-path test for the TGDB scraper."""
    monkeypatch.setattr(scrape_thegamesdb, 'get_scraper_conn', lambda: _FailingConn())
    result = scrape_thegamesdb.apply_metadata_to_game(999, {'game_title': 'No Such Game'})
    assert result is False
