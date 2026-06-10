# =============================================================================
# Pass 38.1 (partial) — _run_fallbacks helper
# =============================================================================
# The FILL GAPS FROM SECONDARY SOURCES block (under `if fill_gaps:`) of
# apply_hybrid_metadata was extracted into _run_fallbacks. The full
# per-scraper fill path is exercised by test_hybrid_scraper.py; these tests
# pin the two pieces of logic that live IN the helper itself:
#   - early-skip when no field is missing (no scraper settings even loaded)
#   - game-title derivation from the ROM filename when no metadata title is
#     present, and that the derived title is what gets handed to the
#     fallback search.
# =============================================================================

import sqlite3

import pytest

from tests._util import REPO_ROOT  # noqa: F401  (ensures sys.path is set)


@pytest.fixture
def cursor(tmp_path):
    """In-memory-ish cursor with a systems↔games join the helper queries
    for the system name before searching fallbacks."""
    conn = sqlite3.connect(str(tmp_path / 'test.db'))
    conn.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT, folder TEXT)")
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, system_id INTEGER, rom_path TEXT, title TEXT)")
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'Genesis', 'genesis')")
    try:
        yield conn
    finally:
        conn.close()


class TestRunFallbacks:
    def test_nothing_missing_skips_all_scraper_work(self, cursor, monkeypatch):
        """When every metadata field is truthy, `missing` is empty and the
        helper must not even load scraper settings — proven by stubbing
        load_scraper_settings to raise and asserting it's never hit."""
        from scraper import hybrid_scraper

        def _boom():
            raise AssertionError("load_scraper_settings should not be called")
        monkeypatch.setattr(hybrid_scraper, 'load_scraper_settings', _boom)

        cursor.execute("INSERT INTO games (id, system_id, rom_path, title) VALUES (1, 1, '/x/Sonic.zip', 'Sonic')")
        cursor.commit()
        c = cursor.cursor()

        metadata = {'title': 'Sonic'}           # only truthy keys → nothing missing
        result = {'sources_used': [], 'filled_fields': []}
        sources_data = {}
        game = {'rom_path': '/x/Sonic.zip', 'title': 'Sonic'}

        hybrid_scraper._run_fallbacks(
            metadata, result, sources_data, game, 1,
            'igdb', 'genesis', None, False, False, c,
        )
        assert sources_data == {}
        assert result['sources_used'] == []

    def test_title_derived_from_rom_filename_feeds_fallback_search(self, cursor, monkeypatch):
        """No metadata title → derive a search title from the ROM filename
        (stripping the (USA) region tag) and hand THAT to the fallback
        scraper search."""
        from scraper import hybrid_scraper

        monkeypatch.setattr(hybrid_scraper, 'load_scraper_settings', lambda: {
            'priority': ['tgdb'],
            'api_keys': {},
            'enabled': {},
        })

        captured = {}

        def _fake_search(title, system_name, limit=5):
            captured['title'] = title
            return []  # no results → helper logs + moves on

        monkeypatch.setattr('scraper.scrape_thegamesdb.search_games', _fake_search)

        cursor.execute(
            "INSERT INTO games (id, system_id, rom_path, title) VALUES (1, 1, '/roms/Rambo (USA).zip', 'Rambo')"
        )
        cursor.commit()
        c = cursor.cursor()

        metadata = {'title': '', 'genre': ''}    # title missing → derive from filename
        result = {'sources_used': [], 'filled_fields': []}
        game = {'rom_path': '/roms/Rambo (USA).zip', 'title': 'Rambo'}

        hybrid_scraper._run_fallbacks(
            metadata, result, {}, game, 1,
            'igdb', 'genesis', None, False, False, c,
        )
        assert captured.get('title') == 'Rambo'
