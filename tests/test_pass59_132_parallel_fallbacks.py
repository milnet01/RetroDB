# =============================================================================
# PASS-59-132 — fallback sources are fetched at once, applied in order
# =============================================================================
# _run_fallbacks fetches every non-AI fallback on its own thread, then applies
# the records one by one in Settings priority order. These tests pin both
# halves: the fetches overlap, and the first source in priority order still
# wins a field even when a later source's fetch finishes first.
# =============================================================================

import sqlite3
import threading
import time

import pytest

from tests._util import REPO_ROOT  # noqa: F401  (ensures sys.path is set)


@pytest.fixture
def cursor(tmp_path):
    conn = sqlite3.connect(str(tmp_path / 'test.db'))
    conn.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT, folder TEXT)")
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, system_id INTEGER, rom_path TEXT, title TEXT)")
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'Genesis', 'genesis')")
    conn.execute("INSERT INTO games (id, system_id, rom_path, title) VALUES (1, 1, '/x/Sonic.zip', 'Sonic')")
    conn.commit()
    try:
        yield conn.cursor()
    finally:
        conn.close()


@pytest.fixture
def fallbacks(monkeypatch):
    """TGDB then IGDB in priority order, each picked from the user's search
    results, with fake detail fetches and applies. Both fetches wait on one
    barrier, which only clears if they run at the same time; one after
    another, it times out and both return nothing."""
    from scraper import hybrid_scraper

    monkeypatch.setattr(hybrid_scraper, 'load_scraper_settings', lambda: {
        'priority': ['tgdb', 'igdb'], 'api_keys': {}, 'enabled': {},
    })
    barrier = threading.Barrier(2, timeout=2)
    finished = []

    def _fetch(name, delay):
        def fetch(source_id):
            try:
                barrier.wait()
            except threading.BrokenBarrierError:
                return None
            time.sleep(delay)
            finished.append(name)
            return {'genre': f'{name}-genre'}
        return fetch

    # TGDB, first in priority, finishes last.
    monkeypatch.setattr(hybrid_scraper, 'fetch_tgdb_extended', _fetch('tgdb', 0.2))
    monkeypatch.setattr(hybrid_scraper, 'fetch_igdb_extended', _fetch('igdb', 0))

    applied = []

    def _apply(name):
        def apply(metadata, data, db_game_id, result, fill_only=False):
            applied.append(name)
            if not metadata['genre']:
                metadata['genre'] = data['genre']
        return apply

    monkeypatch.setattr(hybrid_scraper, 'apply_tgdb_to_metadata', _apply('tgdb'))
    monkeypatch.setattr(hybrid_scraper, 'apply_igdb_to_metadata', _apply('igdb'))
    return hybrid_scraper, finished, applied


def _run(hybrid_scraper, cursor):
    metadata = {'title': 'Sonic', 'genre': None, 'edition': None}
    result = {'sources_used': [], 'filled_fields': []}
    sources_data = {}
    secondary = [{'source': 'tgdb', 'id': 11, 'name': 'Sonic'},
                 {'source': 'igdb', 'id': 22, 'name': 'Sonic'}]
    hybrid_scraper._run_fallbacks(
        metadata, result, sources_data, {'rom_path': '/x/Sonic.zip'}, 1,
        'esde', 'genesis', secondary, False, False, cursor,
    )
    return metadata, result, sources_data


def test_fallback_fetches_run_at_the_same_time(fallbacks, cursor):
    hybrid_scraper, finished, applied = fallbacks
    _, result, sources_data = _run(hybrid_scraper, cursor)
    assert sorted(finished) == ['igdb', 'tgdb']
    assert set(sources_data) == {'tgdb', 'igdb'}
    assert result['sources_used'] == ['TheGamesDB', 'IGDB']


def test_first_source_in_priority_order_wins_a_field(fallbacks, cursor):
    hybrid_scraper, finished, applied = fallbacks
    metadata, _, _ = _run(hybrid_scraper, cursor)
    assert finished == ['igdb', 'tgdb']      # IGDB's fetch ended first...
    assert applied == ['tgdb', 'igdb']       # ...but TGDB applied first
    assert metadata['genre'] == 'tgdb-genre'
