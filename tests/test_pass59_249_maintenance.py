"""PASS-59-249 group I: maintenance and ROM scanning.

Each test pins one finding from the 2026-11-04 audit
(docs/reviews/close-findings-2026-11-05-pass-59-249.md, group I).
"""
import sqlite3
import types
import zipfile

import pytest

from scraper.rom_tools import ArchiveScanner, ROMToolsConfig
from tests._versions_util import vdb  # noqa: F401  (a fixture)


# --- A failed extraction leaves nothing behind ----------------------------------

def test_a_failed_extraction_can_be_retried(tmp_path, monkeypatch):
    import scraper.rom_tools as rom_tools
    archive = tmp_path / 'Game.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        zf.writestr('Game (Disc 1).bin', b'x')
        zf.writestr('Game (Disc 2).bin', b'x')
    real_run = rom_tools.subprocess.run

    def run(cmd, *a, **k):          # listing works; the unpack fails
        if cmd[0] in ('unzip', '7z', 'unrar') and ('-d' in cmd or 'x' in cmd):
            return types.SimpleNamespace(returncode=2, stderr='disk full', stdout='')
        return real_run(cmd, *a, **k)
    monkeypatch.setattr(rom_tools.subprocess, 'run', run)
    scanner = ArchiveScanner(ROMToolsConfig())
    first = scanner.create_m3u_playlist(str(archive), move_to_staging=False)
    assert not first['success'] and 'disk full' in first['error'], first
    assert not (tmp_path / 'Game').exists()
    second = scanner.create_m3u_playlist(str(archive), move_to_staging=False)
    assert 'already exists' not in second['error']


# --- Clear scraped data reads a real true -----------------------------------------

@pytest.mark.parametrize('sent, wanted', [('false', False), ('true', False), (1, False), (True, True)])
def test_clear_scraped_data_deletes_images_only_for_true(monkeypatch, admin_test_client, sent, wanted):
    import routes.maintenance as maintenance
    seen = []
    monkeypatch.setattr(maintenance, 'clear_scraped_data',
                        lambda system_id=None, delete_images=False: seen.append(delete_images) or (0, 0))
    client, csrf = admin_test_client()
    client.post('/api/clear-scraped-data', json={'delete_images': sent}, headers={'X-CSRF-Token': csrf})
    assert seen == [wanted]


# --- A scan whose insert is refused carries on ------------------------------------

class _RacingCursor(sqlite3.Cursor):
    """Its existence check never sees a row: another scan inserts between them."""

    def execute(self, sql, params=()):
        if sql.strip().startswith('SELECT id FROM games WHERE rom_path'):
            return super().execute('SELECT 1 WHERE 0')
        return super().execute(sql, params)


class _RacingConn(sqlite3.Connection):
    def cursor(self, factory=_RacingCursor):
        return super().cursor(factory)


def test_a_scan_carries_on_past_a_rom_another_scan_added(tmp_path, monkeypatch):
    from scraper import scan_roms as scan_mod
    folder = tmp_path / 'roms' / 'genesis'
    folder.mkdir(parents=True)
    (folder / 'systeminfo.txt').write_text('Supported file extensions:\n.md\n', encoding='utf-8')
    (folder / 'A.md').write_bytes(b'x')
    (folder / 'B.md').write_bytes(b'x')
    db = str(tmp_path / 'scan.db')
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT, folder TEXT UNIQUE, logo TEXT)")
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, system_id INTEGER, title TEXT, "
                 "rom_path TEXT UNIQUE, scraped INTEGER, created_at TEXT)")
    conn.execute("INSERT INTO games (system_id, title, rom_path) VALUES (1, 'A', ?)", (str(folder / 'A.md'),))
    conn.commit()
    conn.close()
    monkeypatch.setattr(scan_mod.settings_manager, 'get_effective_path',
                        lambda key, fallback='': str(tmp_path / 'roms') if key == 'rom_path' else fallback)
    monkeypatch.setattr(scan_mod.config, 'STATIC_PATH', str(tmp_path))
    monkeypatch.setattr(scan_mod, 'get_scraper_conn', lambda: sqlite3.connect(db, factory=_RacingConn))
    real_listdir = scan_mod.os.listdir
    monkeypatch.setattr(scan_mod.os, 'listdir', lambda p: sorted(real_listdir(p)))  # A comes first
    assert scan_mod.scan_roms() == 1
    conn = sqlite3.connect(db)
    assert sorted(r[0] for r in conn.execute("SELECT title FROM games")) == ['A', 'B']


def test_there_is_one_scanner():
    from services import rom_scanner
    assert not hasattr(rom_scanner, 'run_inline_scan')


# --- Calculate Storage on a folder game -------------------------------------------

def test_storage_of_a_folder_game_is_its_files(vdb, tmp_path, admin_test_client):  # noqa: F811
    game_dir = tmp_path / 'Game.PS3'
    (game_dir / 'USRDIR').mkdir(parents=True)
    (game_dir / 'PS3_DISC.SFB').write_bytes(b'x' * 10)
    (game_dir / 'USRDIR' / 'EBOOT.BIN').write_bytes(b'x' * 20)
    game_id = vdb.game('Folder Game', rom=None, rom_path=str(game_dir))
    client, csrf = admin_test_client()
    client.post('/api/calculate-storage', headers={'X-CSRF-Token': csrf})
    assert vdb.conn.execute("SELECT file_size FROM games WHERE id = ?", (game_id,)).fetchone()[0] == 30
