"""PASS-59-63, routes group: regression pins for the route-level findings.

Every DB test works on the throwaway schema conftest points RETRODB_DB_PATH
at, inside one system row this module creates and removes.
"""
import os
import re
import sqlite3
from types import SimpleNamespace

import pytest

FOLDER = 'pass5963routes'
VIEWER = {'id': 1, 'username': 'viewer-stub', 'role': 'viewer'}


@pytest.fixture
def db():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                 "VALUES (1, 'admin-stub', 'x', 'admin')")
    conn.execute("INSERT INTO systems (name, folder) VALUES ('Pass 59-63', ?)", (FOLDER,))
    sid = conn.execute("SELECT id FROM systems WHERE folder = ?", (FOLDER,)).fetchone()[0]
    conn.commit()
    yield SimpleNamespace(conn=conn, sid=sid)
    conn.execute("DELETE FROM system_controllers WHERE system_id = ?", (sid,))
    conn.execute("DELETE FROM controllers WHERE name LIKE 'P5963 %'")
    conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
    conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
    conn.commit()
    conn.close()


def _game(d, title, **cols):
    cols = {'rom_path': f'/roms/{FOLDER}/{title}.zip', **cols}
    names = ', '.join(cols)
    cur = d.conn.execute(
        f"INSERT INTO games (system_id, title, {names}) VALUES (?, ?, {', '.join('?' * len(cols))})",
        (d.sid, title, *cols.values()))
    d.conn.commit()
    return cur.lastrowid


def _row(d, game_id):
    return d.conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()


# 1 — JSON edit with a blank title keeps the title and saves the rest.
def test_json_edit_blank_title_keeps_title(db, admin_test_client):
    gid = _game(db, 'Keep Me')
    client, csrf = admin_test_client()
    resp = client.post(f'/api/game/{gid}/edit', json={'title': '  ', 'publisher': 'New Pub'},
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    row = _row(db, gid)
    assert (row['title'], row['publisher']) == ('Keep Me', 'New Pub')


# 2 — AI fill assigns each column once.
def test_ai_fill_sets_each_column_once(db, admin_test_client, monkeypatch):
    import routes.games_ai as games_ai
    import scraper.scrape_ai as scrape_ai
    gid = _game(db, 'Lonely Game')
    monkeypatch.setattr(scrape_ai, 'get_game_details',
                        lambda *a, **k: {'franchise': 'Standalone'})
    seen = []
    real_execute = games_ai.execute

    def _spy(sql, args=()):
        seen.append(sql)
        return real_execute(sql, args)

    monkeypatch.setattr(games_ai, 'execute', _spy)
    client, csrf = admin_test_client()
    resp = client.post(f'/api/game/{gid}/ai-fill', headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    update = next(s for s in seen if s.startswith('UPDATE games SET'))
    cols = re.findall(r'(\w+) = \?', update.split(' WHERE ')[0])
    assert len(cols) == len(set(cols)), cols
    assert _row(db, gid)['franchise'] is None


# 3 — a viewer cannot write the library-global completion_status.
def test_viewer_cannot_set_completion(db, admin_test_client):
    gid = _game(db, 'Shared Game', completion_status='not_started')
    client, csrf = admin_test_client(user=VIEWER)
    resp = client.post(f'/api/game/{gid}/completion', json={'status': 'completed'},
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 403
    assert _row(db, gid)['completion_status'] == 'not_started'


# 4 — restart drains jobs first, and the frozen argv names the binary once.
@pytest.mark.parametrize('frozen, argv, expected', [
    (True, ['/opt/retrodb', '--x'], ['/opt/retrodb', '--x']),
    (False, ['app.py', '--x'], ['/usr/bin/python3', 'app.py', '--x']),
])
def test_restart_drains_then_execs(admin_test_client, monkeypatch, frozen, argv, expected):
    import routes.maintenance as maint
    import services.jobs.base as jobs_base
    calls = []
    fake_sys = SimpleNamespace(executable='/opt/retrodb' if frozen else '/usr/bin/python3',
                               argv=argv)
    if frozen:
        fake_sys.frozen = True

    class _InlineThread:
        def __init__(self, target, **_kw):
            self._target = target

        def start(self):
            self._target()

    monkeypatch.setattr(maint, 'sys', fake_sys)
    monkeypatch.setattr(maint, 'threading', SimpleNamespace(Thread=_InlineThread))
    monkeypatch.setattr(maint, 'time', SimpleNamespace(sleep=lambda _s: None))
    monkeypatch.setattr(jobs_base, 'request_shutdown',
                        lambda timeout=5.0: calls.append('drain'))
    monkeypatch.setattr(maint.os, 'execv', lambda exe, args: calls.append(('execv', exe, args)))
    client, csrf = admin_test_client()
    resp = client.post('/api/restart', headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200
    assert calls == ['drain', ('execv', fake_sys.executable, expected)]


# 5 — the secret-key ladder self-heals on a read-only or garbled data dir.
def test_secret_key_survives_unwritable_data_dir(tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.delenv('RETRODB_SECRET_KEY', raising=False)
    monkeypatch.setattr(app_module.config, 'BASE_DIR', str(tmp_path / 'ro'))

    def _deny(*_a, **_k):
        raise PermissionError('read-only file system')

    monkeypatch.setattr(app_module.os, 'makedirs', _deny)
    assert re.fullmatch(r'[0-9a-f]{64}', app_module._get_secret_key())


def test_secret_key_survives_undecodable_file(tmp_path, monkeypatch):
    import app as app_module
    monkeypatch.delenv('RETRODB_SECRET_KEY', raising=False)
    monkeypatch.setattr(app_module.config, 'BASE_DIR', str(tmp_path))
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data' / '.secret_key').write_bytes(b'\xff\xfe\x00garbage')
    assert re.fullmatch(r'[0-9a-f]{64}', app_module._get_secret_key())


# 7 — the bonus-disc sweep is one transaction: a failure flags nothing.
def test_bonus_sweep_is_atomic(db, admin_test_client, monkeypatch):
    import routes.bonus_discs as bonus
    _game(db, 'Foo')
    ids = [_game(db, 'Foo (Bonus Disc)'), _game(db, 'Bar (Bonus Disc)')]
    calls = []

    def _fail_second(value):
        calls.append(value)
        if len(calls) == 2:
            raise RuntimeError('interrupted')
        return value

    monkeypatch.setattr(bonus, 'escape_like', _fail_second)
    client, csrf = admin_test_client()
    client.post(f'/api/bonus-discs/auto-link?system_id={db.sid}', headers={'X-CSRF-Token': csrf})
    assert len(calls) == 2
    assert [_row(db, i)['is_bonus_disc'] for i in ids] == [0, 0]


# 8 — the plural set-default endpoint refuses an unknown controller.
def test_plural_default_controller_checks_existence(db, admin_test_client):
    cur = db.conn.execute("INSERT INTO controllers (name) VALUES ('P5963 Pad')")
    cid = cur.lastrowid
    db.conn.execute("INSERT INTO system_controllers (system_id, controller_id, is_default) "
                    "VALUES (?, ?, 1)", (db.sid, cid))
    db.conn.commit()
    client, csrf = admin_test_client()
    resp = client.post(f'/api/systems/{db.sid}/default-controllers',
                       json={'controller_ids': [987654321]}, headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 404
    still = db.conn.execute("SELECT is_default FROM system_controllers "
                            "WHERE system_id = ? AND controller_id = ?", (db.sid, cid)).fetchone()
    assert still['is_default'] == 1


# 9 — CLZ-imported genres land in their canonical hyphenated form.
def test_clz_import_normalises_genre(db, admin_test_client):
    client, csrf = admin_test_client()
    resp = client.post('/api/clz-import/import', headers={'X-CSRF-Token': csrf}, json={
        'games': [{'title': 'P5963 Clz Shooter', 'system_id': db.sid,
                   'system_folder': FOLDER, 'genre': 'First Person Shooter'}]})
    assert resp.get_json()['imported'] == 1
    row = db.conn.execute("SELECT genre FROM games WHERE system_id = ? AND title = ?",
                          (db.sid, 'P5963 Clz Shooter')).fetchone()
    assert row['genre'] == 'First-Person-Shooter'


# 10 — the naming reports read their settings once, not once per game.
# (build_filename -> services.game_utils.apply_article_placement still reads
# article_placement per suggested name; that read is in services/, not here.)
@pytest.mark.parametrize('endpoint', ['/api/reports/naming-check', '/api/reports/name-mismatch'])
def test_reports_read_settings_outside_loop(db, admin_test_client, monkeypatch, endpoint):
    import settings_manager
    for i in range(4):
        _game(db, f'Alpha Game {i}', rom_path=f'/roms/{FOLDER}/Totally Other {i} (USA).zip')
    calls = []
    real = settings_manager.get_setting

    def _count(key, default=None):
        calls.append(key)
        return real(key, default)

    client, _csrf = admin_test_client()
    monkeypatch.setattr(settings_manager, 'get_setting', _count)
    resp = client.get(endpoint)
    assert resp.status_code == 200
    assert calls.count('naming_convention') == 1, calls
