"""PASS-59-249 group H: database, settings and restore.

Each test pins one finding from the 2026-11-04 audit
(docs/reviews/close-findings-2026-11-05-pass-59-249.md, group H).
"""
import os
import sqlite3
import sys
import threading
import time

import pytest

import config
import settings_manager
from services import migrations
from tests._versions_util import vdb  # noqa: F401  (a fixture)
from tests.test_box_faces import _box, _png, game, images  # noqa: F401  (fixtures)


# --- Restore ----------------------------------------------------------------------

def test_a_restore_reaches_connections_already_open(tmp_path, monkeypatch, admin_test_client):
    live = tmp_path / 'roms.db'
    src = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    dst = sqlite3.connect(live)
    src.backup(dst)
    src.close()
    dst.execute("PRAGMA journal_mode = WAL")
    dst.execute("CREATE TABLE probe (x TEXT)")
    dst.execute("INSERT INTO probe VALUES ('backup')")
    dst.commit()
    (tmp_path / 'backups').mkdir()
    saved = sqlite3.connect(tmp_path / 'backups' / 'probe.db')
    dst.backup(saved)
    saved.close()
    dst.execute("UPDATE probe SET x = 'live'")
    dst.commit()
    dst.close()

    monkeypatch.setattr(config, 'DB_PATH', str(live))
    other = sqlite3.connect(live)        # a job or request already holding the DB
    assert other.execute("SELECT x FROM probe").fetchone()[0] == 'live'
    client, csrf = admin_test_client()
    reply = client.post('/api/restore/probe.db', headers={'X-CSRF-Token': csrf}).get_json()
    assert reply['success'], reply
    assert other.execute("SELECT x FROM probe").fetchone()[0] == 'backup'
    assert other.execute("PRAGMA integrity_check").fetchone()[0] == 'ok'
    other.close()


# --- Migrations -------------------------------------------------------------------

def test_migration_030_survives_its_helpers_going_missing(monkeypatch):
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, description TEXT)")
    conn.execute("INSERT INTO games VALUES (1, 'a &amp; b')")
    monkeypatch.setitem(sys.modules, 'scraper.scrape_ai', None)
    migrations._load('030_tidy_stored_text').apply(conn)


@pytest.mark.parametrize('name', ['001_baseline', '012_emulators'])
def test_column_helpers_hide_only_a_duplicate_column(name):
    helper = migrations._load(name)._add_column_if_missing
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE t (a TEXT)")
    helper(conn.cursor(), 't', 'a', 'TEXT')
    with pytest.raises(sqlite3.OperationalError):
        helper(conn.cursor(), 'missing_table', 'a', 'TEXT')


def test_baseline_defaults_use_single_quotes():
    source = open(migrations._load('001_baseline').__file__, encoding='utf-8').read()
    assert 'DEFAULT "' not in source


def test_deleting_a_game_drops_its_queue_and_setting_rows(vdb):  # noqa: F811
    game_id = vdb.game('Orphan Probe')
    emulator_id = vdb.conn.execute("SELECT id FROM emulators LIMIT 1").fetchone()[0]
    vdb.conn.execute("INSERT INTO pending_upscales (game_id) VALUES (?)", (game_id,))
    vdb.conn.execute("INSERT INTO emulator_setting_choices (emulator_id, scope, scope_id, setting, value) "
                     "VALUES (?, 'game', ?, 'probe', '1')", (emulator_id, game_id))
    vdb.conn.execute("INSERT INTO emulator_setting_choices (emulator_id, scope, scope_id, setting, value) "
                     "VALUES (?, 'system', ?, 'probe', '1')", (emulator_id, game_id))
    vdb.conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
    vdb.conn.commit()
    try:
        assert vdb.conn.execute("SELECT COUNT(*) FROM pending_upscales WHERE game_id = ?",
                                (game_id,)).fetchone()[0] == 0
        assert [r[0] for r in vdb.conn.execute(
            "SELECT scope FROM emulator_setting_choices WHERE setting = 'probe' AND scope_id = ?",
            (game_id,))] == ['system']
    finally:
        vdb.conn.execute("DELETE FROM emulator_setting_choices WHERE setting = 'probe'")
        vdb.conn.execute("DELETE FROM pending_upscales WHERE game_id = ?", (game_id,))
        vdb.conn.commit()


def test_deleting_a_game_deletes_its_box_faces(game, images, admin_test_client):  # noqa: F811
    from services import box_faces
    box_faces.import_box_file(game, {
        'S.box.json': _box(), 'S.front.png': _png(270, 380),
        'S.spine.png': _png(28, 380), 'S.back.png': _png(270, 380)})
    folder = images / 'box_faces'
    assert any(n.startswith(f'{game}_') for n in os.listdir(folder))
    client, csrf = admin_test_client()
    assert client.post(f'/api/delete-game/{game}', headers={'X-CSRF-Token': csrf}).get_json()['success']
    assert not any(n.startswith(f'{game}_') for n in os.listdir(folder))


# --- Settings ---------------------------------------------------------------------

def test_two_set_settings_at_once_keep_both(monkeypatch):
    store = {}
    first = threading.Event()

    def load():
        copy = dict(store)
        if not first.is_set():
            first.set()
            time.sleep(0.3)      # the second save lands while this one holds a stale copy
        return copy

    def save(settings):
        store.clear()
        store.update(settings)
        return True
    monkeypatch.setattr(settings_manager, 'load_settings', load)
    monkeypatch.setattr(settings_manager, 'save_settings', save)
    a = threading.Thread(target=settings_manager.set_setting, args=('a', 1))
    a.start()
    first.wait(1)
    settings_manager.set_setting('b', 2)
    a.join()
    assert store == {'a': 1, 'b': 2}


@pytest.mark.parametrize('value', [5, None, ['x']])
def test_effective_path_ignores_a_value_that_is_not_text(monkeypatch, value):
    monkeypatch.setattr(settings_manager, 'load_settings', lambda: {'rom_path': value})
    assert settings_manager.get_effective_path('rom_path', 'fallback') == 'fallback'
