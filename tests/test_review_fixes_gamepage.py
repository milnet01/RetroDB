"""Review follow-ups for the game page, RPCS3 compatibility, the Systems
page's unscraped count and uploads in the edit window."""
import io
import sqlite3
from pathlib import Path

import pytest

from services import rpcs3_compat
from tests._versions_util import vdb  # noqa: F401 — fixture


def _ps3_game():
    return {'id': 1, 'system_folder': 'ps3', 'rom_path': '/roms/ps3/Game.iso',
            'disc_serial': None}


# --- the game page's RPCS3 serial read -------------------------------------

def test_no_compat_list_reads_no_disc(monkeypatch):
    # With no list the badge can never show, so the disc is not read.
    monkeypatch.setattr(rpcs3_compat, 'available', lambda: False)

    def boom(_game):
        raise AssertionError('disc read without a compatibility list')
    monkeypatch.setattr('services.standalone_settings.disc_ids', boom)
    game = _ps3_game()
    rpcs3_compat.ensure_serial(game)
    assert game['disc_serial'] is None


def test_locked_database_does_not_break_the_page(monkeypatch):
    monkeypatch.setattr(rpcs3_compat, 'available', lambda: True)

    def locked(_game):
        raise sqlite3.OperationalError('database is locked')
    monkeypatch.setattr('services.standalone_settings.disc_ids', locked)
    game = _ps3_game()
    rpcs3_compat.ensure_serial(game)
    assert game['disc_serial'] is None


def test_compat_lookup_never_searches_the_working_directory(tmp_path, monkeypatch):
    monkeypatch.setattr(rpcs3_compat, 'query', lambda *a, **k: [])
    monkeypatch.chdir(tmp_path)
    dirs = rpcs3_compat._candidate_dirs()
    assert dirs
    assert all(Path(d).is_absolute() for d in dirs), dirs


# --- Systems page: unscraped count matches the Unscraped filter ------------

def test_systems_unscraped_count_counts_version_groups(vdb, admin_test_client, monkeypatch):
    from services.game_query import _build_games_query
    from services.database import query
    group = vdb.conn.execute("INSERT INTO version_groups (created_at) VALUES ('x')").lastrowid
    vdb.conn.commit()
    vdb.game('Pair', rom='Pair (USA).zip', scraped=0, version_group_id=group)
    vdb.game('Pair', rom='Pair (Europe).zip', scraped=0, version_group_id=group)
    vdb.game('Alone', scraped=0)
    vdb.game('Done', scraped=1)

    seen = {}

    def capture(_template, **ctx):
        seen.update(ctx)
        return ''
    monkeypatch.setattr('routes.systems.render_template', capture)
    client, _ = admin_test_client()
    assert client.get('/systems').status_code == 200
    row = next(s for s in seen['systems'] if s['id'] == vdb.sid)

    sql, values = _build_games_query({'system': vdb.sid, '_unscraped': True}, count_only=True)
    cards = query(sql, values, one=True)['total']
    assert cards == 2
    assert row['missing_count'] == cards


# --- uploads: the replaced file outlives a failed save ---------------------

def _post_boxart(client, csrf, game_id):
    return client.post(f'/game/{game_id}', data={
        'action': 'edit_metadata', 'edit_title': 'Boxed',
        'custom_boxart': (io.BytesIO(b'img'), 'new.png'),
    }, headers={'X-CSRF-Token': csrf}, content_type='multipart/form-data')


@pytest.fixture
def upload_spy(monkeypatch):
    removed = []
    monkeypatch.setattr('routes.games.save_upload',
                        lambda f, *a, **k: 'custom_new.png' if f and f.filename else None)
    monkeypatch.setattr('routes.games.remove_media_file',
                        lambda name, kind: removed.append((name, kind)))
    return removed


def test_failed_update_keeps_the_replaced_boxart(vdb, admin_test_client, monkeypatch, upload_spy):
    import routes.games as games_routes
    real_execute = games_routes.execute

    def failing(sql, args=()):
        if 'UPDATE games SET' in sql and 'boxart_3d = NULLIF' in sql:
            raise sqlite3.OperationalError('database is locked')
        return real_execute(sql, args)
    monkeypatch.setattr(games_routes, 'execute', failing)
    game_id = vdb.game('Boxed', boxart='old.png')
    client, csrf = admin_test_client()
    _post_boxart(client, csrf, game_id)
    assert upload_spy == []
    assert vdb.conn.execute("SELECT boxart FROM games WHERE id = ?",
                            (game_id,)).fetchone()[0] == 'old.png'


def test_saved_upload_removes_the_replaced_boxart(vdb, admin_test_client, upload_spy):
    game_id = vdb.game('Boxed', boxart='old.png')
    client, csrf = admin_test_client()
    _post_boxart(client, csrf, game_id)
    assert upload_spy == [('old.png', 'boxart')]
    assert vdb.conn.execute("SELECT boxart FROM games WHERE id = ?",
                            (game_id,)).fetchone()[0] == 'custom_new.png'
