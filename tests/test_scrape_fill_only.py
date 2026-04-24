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
    before we assert on it."""

    def __init__(self, conn):
        self._conn = conn

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
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
def _noop_download(monkeypatch):
    """Neutralise image-download helpers so tests don't touch the network."""
    monkeypatch.setattr(scrape_igdb, 'download_image', lambda *a, **kw: None)
    monkeypatch.setattr(scrape_thegamesdb, '_download_tgdb_image', lambda *a, **kw: None, raising=False)


def test_igdb_apply_preserves_existing_values_when_response_is_empty(monkeypatch, _noop_download):
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


def test_tgdb_apply_preserves_existing_values_when_response_is_empty(monkeypatch, _noop_download):
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
