"""Regression pins: scraper fetches must not invent values that the fill-only
merge then keeps for good (an ID written as a name, a guessed player count)."""

import pytest


@pytest.fixture
def tgdb(monkeypatch):
    from scraper import scrape_thegamesdb as mod
    mod.clear_caches()
    yield mod
    mod.clear_caches()


def test_tgdb_unresolved_ids_are_not_written_as_names(tgdb, monkeypatch):
    monkeypatch.setattr(tgdb, '_tgdb_request', lambda *a, **kw: None)
    assert tgdb._resolve_names([6431], tgdb._get_publishers) == ''
    assert tgdb._resolve_genre_names([999999]) == []
    # The local genre map still names a known id.
    assert tgdb._resolve_genre_names([1]) == ['Action']


def test_tgdb_failed_lookup_is_retried_not_cached_empty(tgdb, monkeypatch):
    calls = []

    class _Resp:
        status_code = 200

        @staticmethod
        def json():
            return {'data': {'publishers': {'7': {'id': 7, 'name': 'Sega'}}}}

    def _request(*a, **kw):
        calls.append(1)
        return None if len(calls) == 1 else _Resp()

    monkeypatch.setattr(tgdb, '_tgdb_request', _request)
    assert tgdb._get_publishers() == {}
    # Within the retry window: no second request.
    assert tgdb._get_publishers() == {}
    assert len(calls) == 1
    tgdb._lookup_failed_at['publishers'] = 0
    assert tgdb._resolve_names([7], tgdb._get_publishers) == 'Sega'
    # Cached once fetched.
    tgdb._get_publishers()
    assert len(calls) == 2


def test_rawg_players_unknown_without_a_player_tag(monkeypatch):
    from scraper import scrape_rawg

    def _req(endpoint, params=None, max_retries=2):
        if endpoint == 'games/1':
            return {'id': 1, 'name': 'Myst', 'tags': [{'name': 'Puzzle'}]}
        return None

    monkeypatch.setattr(scrape_rawg, '_make_request', _req)
    monkeypatch.setattr(scrape_rawg, 'rate_limit', lambda *a: None)
    assert scrape_rawg.get_game_details(1)['players'] is None


@pytest.fixture
def esde_db(tmp_path, monkeypatch):
    import sqlite3
    from services import migrations
    from scraper import scrape_esde
    path = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(path)
    migrations.apply_pending(conn)
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'NES', 'nes')")
    conn.execute("INSERT INTO games (id, system_id, title, rom_path, players, modes) "
                 "VALUES (1, 1, 'Contra', '/roms/nes/Contra (USA).nes', 2, "
                 "'Single-Player, Local Multiplayer')")
    conn.commit()
    conn.close()

    def connect():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setattr(scrape_esde, 'get_scraper_conn', connect)
    monkeypatch.setattr(scrape_esde, '_get_esde_gamelists_path', lambda: None)
    monkeypatch.setattr(scrape_esde, '_get_esde_media_path', lambda: None)
    return connect


def test_esde_row_without_players_keeps_curated_players_and_modes(esde_db):
    from scraper import scrape_esde
    assert scrape_esde.apply_esde_metadata(1, {'name': 'Contra'}) is True
    c = esde_db()
    row = c.execute("SELECT players, modes FROM games WHERE id = 1").fetchone()
    c.close()
    assert row['players'] == 2
    assert row['modes'] == 'Single-Player, Local Multiplayer'


def test_esde_full_path_match_beats_earlier_filename_match(monkeypatch):
    from scraper import scrape_esde
    games = [
        {'path': './Game A/disc1.chd', 'name': 'Game A'},
        {'path': './Game B/disc1.chd', 'name': 'Game B'},
    ]
    monkeypatch.setattr(scrape_esde, 'find_gamelist_xml', lambda folder: '/x/gamelist.xml')
    monkeypatch.setattr(scrape_esde, 'parse_gamelist_xml', lambda p: list(games))
    got = scrape_esde.fetch_esde_game_details('./Game B/disc1.chd', 'psx')
    assert got['name'] == 'Game B'
    # A bare filename still finds the first holder of that name.
    assert scrape_esde.fetch_esde_game_details('disc1.chd', 'psx')['name'] == 'Game A'
    assert got['players'] == ''



def test_scan_finds_svg_only_system_logo_and_keeps_existing(tmp_path, monkeypatch):
    import sqlite3
    from scraper import scan_roms as scan_mod
    rom_root = tmp_path / 'roms'
    (rom_root / 'genesis').mkdir(parents=True)
    (rom_root / 'genesis' / 'systeminfo.txt').write_text(
        'Supported file extensions:\n.md\n', encoding='utf-8')
    (rom_root / 'genesis' / 'Sonic (USA).md').write_bytes(b'x')
    (rom_root / 'nes').mkdir()
    (rom_root / 'nes' / 'systeminfo.txt').write_text(
        'Supported file extensions:\n.nes\n', encoding='utf-8')
    static = tmp_path / 'static'
    (static / 'images' / 'systems').mkdir(parents=True)
    (static / 'images' / 'systems' / 'genesis.svg').write_text('<svg/>')

    db = str(tmp_path / 'scan.db')
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT, "
                 "folder TEXT UNIQUE, logo TEXT)")
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, system_id INTEGER, "
                 "title TEXT, rom_path TEXT, scraped INTEGER, created_at TEXT)")
    conn.execute("INSERT INTO systems (name, folder, logo) VALUES ('NES', 'nes', 'custom.webp')")
    conn.commit()
    conn.close()

    monkeypatch.setattr(scan_mod.settings_manager, 'get_effective_path',
                        lambda key, fallback='': str(rom_root) if key == 'rom_path' else fallback)
    monkeypatch.setattr(scan_mod.config, 'STATIC_PATH', str(static))
    monkeypatch.setattr(scan_mod, 'get_scraper_conn', lambda: sqlite3.connect(db))
    assert scan_mod.scan_roms() == 1

    conn = sqlite3.connect(db)
    logos = dict(conn.execute("SELECT folder, logo FROM systems").fetchall())
    conn.close()
    assert logos == {'genesis': 'genesis.svg', 'nes': 'custom.webp'}
