"""Regression pins for the PR #21 review follow-up: logo refresh roots,
bonus-disc unmark, and 400 (not 500) on a bad JSON body.
"""
import os
import sqlite3
from types import SimpleNamespace

import pytest

FOLDER = 'reviewfollowup'


@pytest.fixture
def db():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT INTO systems (name, folder) VALUES ('Review Followup', ?)", (FOLDER,))
    sid = conn.execute("SELECT id FROM systems WHERE folder = ?", (FOLDER,)).fetchone()[0]
    conn.commit()
    yield SimpleNamespace(conn=conn, sid=sid)
    conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
    conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
    conn.commit()
    conn.close()


def _game(d, title, **cols):
    cols = {'rom_path': f'/roms/{FOLDER}/{title}.zip', **cols}
    cur = d.conn.execute(
        f"INSERT INTO games (system_id, title, {', '.join(cols)}) "
        f"VALUES (?, ?, {', '.join('?' * len(cols))})",
        (d.sid, title, *cols.values()))
    d.conn.commit()
    return cur.lastrowid


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, 'wb').close()


@pytest.mark.parametrize('bundled', [False, True])
def test_refresh_logos_finds_imported_logo_first(db, admin_test_client, monkeypatch,
                                                 tmp_path, bundled):
    """An ES-DE logo imported under IMAGE_PATH is found, and wins over a bundled one."""
    import config
    image_path, static_path = tmp_path / 'user_images', tmp_path / 'bundle_static'
    monkeypatch.setattr(config, 'IMAGE_PATH', str(image_path))
    monkeypatch.setattr(config, 'STATIC_PATH', str(static_path))
    _touch(str(image_path / 'systems' / f'{FOLDER}.webp'))
    if bundled:
        _touch(str(static_path / 'images' / 'systems' / f'{FOLDER}.png'))

    client, csrf = admin_test_client()
    resp = client.post('/api/refresh-system-logos', headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    logo = db.conn.execute("SELECT logo FROM systems WHERE id = ?", (db.sid,)).fetchone()['logo']
    assert logo == f'{FOLDER}.webp'


def test_unmark_bonus_disc_clears_parent(db, admin_test_client):
    parent = _game(db, 'Parent Game')
    bonus = _game(db, 'Parent Game (Bonus Disc)', is_bonus_disc=1, parent_game_id=parent)
    client, csrf = admin_test_client()
    resp = client.post('/api/bonus-discs/mark', json={'game_id': bonus, 'is_bonus': False},
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200
    row = db.conn.execute("SELECT is_bonus_disc, parent_game_id FROM games WHERE id = ?",
                          (bonus,)).fetchone()
    assert (row['is_bonus_disc'], row['parent_game_id']) == (0, None)


@pytest.mark.parametrize('method,url', [
    ('post', '/api/update-system-type'),
    ('post', '/api/dropdown-options/region'),
    ('post', '/api/settings/paths'),
    ('post', '/api/controllers'),
    ('put', '/api/controllers/1'),
    ('post', '/api/systems/1/default-controllers'),
    ('post', '/api/systems/1/default-controller'),
    ('post', '/api/bonus-discs/link'),
    ('post', '/api/bonus-discs/mark'),
])
@pytest.mark.parametrize('body', [None, [1, 2], 'text'])
def test_non_object_json_body_is_400(admin_test_client, method, url, body):
    client, csrf = admin_test_client()
    kwargs = {'data': 'null', 'content_type': 'application/json'} if body is None else {'json': body}
    resp = getattr(client, method)(url, headers={'X-CSRF-Token': csrf}, **kwargs)
    assert resp.status_code == 400, resp.get_data(as_text=True)[:300]


@pytest.mark.parametrize('method,url,body', [
    ('post', '/api/update-system-type', {'system_id': 999999999, 'system_type': None}),
    ('post', '/api/dropdown-options/region', {'value': None}),
    ('post', '/api/controllers', {'name': None, 'manufacturer': None}),
    ('put', '/api/controllers/999999999', {'name': 'x', 'description': None, 'button_layout': None}),
])
def test_null_string_field_is_not_500(admin_test_client, method, url, body):
    client, csrf = admin_test_client()
    resp = getattr(client, method)(url, json=body, headers={'X-CSRF-Token': csrf})
    assert resp.status_code != 500, resp.get_data(as_text=True)[:300]
