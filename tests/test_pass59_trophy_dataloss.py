"""PASS-59-117: three trophy paths that destroyed stored data.

(a) The PSN bulk refresh wrote zero counts when PSN omitted a count block.
(b) A failed RA game-list request unlinked every game on that console.
(c) /api/clear-ra-data deleted Steam and Xbox progress rows too.

No network call is made: PSN titles and RA replies are built by hand.
"""
import os
import sqlite3
from types import SimpleNamespace

import pytest

from tests.test_pass59_psn_counts import NPWR, STORED, _counts, _row, _title
from tests.test_pass59_psn_counts import db  # noqa: F401 — fixture

RA_FOLDER = 'snes'


def _bulk_sync(conn, title):
    from services.jobs.psn_refresh import PSNRefreshJob
    job = PSNRefreshJob()
    job._user_id = 1
    psn_game = conn.execute("SELECT * FROM psn_games WHERE npwr_id = ?", (NPWR,)).fetchone()
    job._sync_game_trophies(None, NPWR, psn_game, title, conn)


def test_bulk_refresh_keeps_counts_when_blocks_missing(db):  # noqa: F811
    _bulk_sync(db, _title())
    assert _row(db) == STORED


def test_bulk_refresh_still_writes_real_counts(db):  # noqa: F811
    _bulk_sync(db, _title(_counts(1, 3, 5, 7), _counts(1, 4, 6, 9)))
    row = _row(db)
    assert row['earned_gold'] == 3 and row['earned_trophies'] == 16
    assert row['progress'] == 80


@pytest.fixture
def ra_db():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                 "VALUES (1, 'admin-stub', 'x', 'admin')")
    sys_id = conn.execute("INSERT INTO systems (name, folder) VALUES ('SNES 59117', ?)",
                          (RA_FOLDER,)).lastrowid
    ids = {}
    # The Steam game is also RA-linked: the per-system clear must still keep
    # its Steam progress row.
    for source, ra_id in (('ra', 751), ('steam', 752), ('xbox', None)):
        gid = conn.execute(
            "INSERT INTO games (system_id, title, rom_path, ra_game_id, has_retroachievements) "
            "VALUES (?, ?, ?, ?, ?)",
            (sys_id, f'Game {source}', f'/roms/{source}.sfc', ra_id, int(bool(ra_id)))).lastrowid
        conn.execute("INSERT INTO game_achievement_progress (game_id, user_id, source) "
                     "VALUES (?, 1, ?)", (gid, source))
        ids[source] = gid
    conn.commit()
    yield conn, sys_id, ids
    conn.execute("DELETE FROM game_achievement_progress WHERE game_id IN (?, ?, ?)",
                 list(ids.values()))
    conn.execute("DELETE FROM games WHERE system_id = ?", (sys_id,))
    conn.execute("DELETE FROM systems WHERE id = ?", (sys_id,))
    conn.commit()
    conn.close()


def _ra_refresh(monkeypatch, sys_id, get):
    import requests
    import services.jobs.ra_refresh as ra_refresh
    monkeypatch.setattr(ra_refresh, '_get_ra_credentials', lambda: ('user', 'key'))
    monkeypatch.setattr(ra_refresh, 'shutdown_requested', SimpleNamespace(wait=lambda s: None))
    monkeypatch.setattr(requests, 'get', get)
    job = ra_refresh.RARefreshJob()
    job.system_id = sys_id
    job.running = True
    job._run_refresh()
    return job


def _ra_link(conn, game_id):
    row = conn.execute("SELECT ra_game_id, has_retroachievements FROM games WHERE id = ?",
                       (game_id,)).fetchone()
    return row['ra_game_id'], row['has_retroachievements']


@pytest.mark.parametrize('failure', ['http_503', 'network_error'])
def test_failed_ra_list_fetch_keeps_links(ra_db, monkeypatch, failure):
    conn, sys_id, ids = ra_db

    def get(*a, **k):
        if failure == 'network_error':
            raise OSError('connection reset')
        return SimpleNamespace(status_code=503, json=lambda: [])

    job = _ra_refresh(monkeypatch, sys_id, get)
    assert _ra_link(conn, ids['ra']) == (751, 1)
    assert job.failed_count == 3 and job.skipped_count == 0


def test_empty_ra_list_still_unlinks(ra_db, monkeypatch):
    """Control: a list that really came back without this game unlinks it."""
    conn, sys_id, ids = ra_db
    job = _ra_refresh(monkeypatch, sys_id,
                      lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: []))
    assert _ra_link(conn, ids['ra']) == (None, 0)
    assert job.skipped_count == 3


@pytest.mark.parametrize('per_system', [False, True])
def test_clear_ra_data_keeps_steam_and_xbox_rows(ra_db, admin_test_client, per_system):
    conn, sys_id, ids = ra_db
    client, csrf = admin_test_client()
    url = f'/api/clear-ra-data/{sys_id}' if per_system else '/api/clear-ra-data'
    assert client.post(url, headers={'X-CSRF-Token': csrf}).status_code == 200
    left = {r['source'] for r in conn.execute(
        "SELECT source FROM game_achievement_progress WHERE game_id IN (?, ?, ?)",
        list(ids.values()))}
    assert left == {'steam', 'xbox'}
