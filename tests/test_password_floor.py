"""PASS-59-121: every password form holds the server's 12-character floor.

The forced-change page and the setup wizard checked 4 characters in the
browser, and /api/setup checked nothing, so a first-run admin password
could be a single character.
"""

import re
import sqlite3
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'


def _setup_client(monkeypatch, tmp_path):
    import app as app_module
    monkeypatch.setattr(app_module.config, 'BASE_DIR', str(tmp_path))
    monkeypatch.setattr('app.atomic_write_json', lambda *a, **k: None)
    monkeypatch.setattr('app.settings_manager.load_settings', lambda: {})
    monkeypatch.setattr('app.settings_manager.save_settings', lambda s: True)
    monkeypatch.setattr(app_module.config, 'ROM_PATH', '', raising=False)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'tok'
    return app_module, client


def _admin_rows(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            "SELECT id, username, password_hash FROM users WHERE role = 'admin'"
        ).fetchall()
    finally:
        conn.close()


def test_setup_refuses_a_short_admin_password(monkeypatch, tmp_path):
    app_module, client = _setup_client(monkeypatch, tmp_path)
    before = _admin_rows(app_module.config.DB_PATH)
    resp = client.post('/api/setup', json={
        'license_accepted': True,
        'admin_username': 'boss',
        'admin_password': 'abcde',
    }, headers={'X-CSRF-Token': 'tok'})
    body = resp.get_json()
    assert resp.status_code == 422, body
    assert body['success'] is False
    assert _admin_rows(app_module.config.DB_PATH) == before


def _snapshot_users(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute("SELECT * FROM users")]
    finally:
        conn.close()


def _restore_users(db_path, rows):
    """Put every saved users row back as it was (setup renames the admin)."""
    conn = sqlite3.connect(db_path)
    try:
        for row in rows:
            cols = [c for c in row if c != 'id']
            conn.execute("UPDATE users SET " + ", ".join(f"{c} = ?" for c in cols)
                         + " WHERE id = ?", [row[c] for c in cols] + [row['id']])
        conn.commit()
    finally:
        conn.close()


@pytest.fixture
def restore_users():
    import config
    saved = _snapshot_users(config.DB_PATH)
    yield
    _restore_users(config.DB_PATH, saved)


def test_setup_accepts_a_12_character_admin_password(monkeypatch, tmp_path, restore_users):
    app_module, client = _setup_client(monkeypatch, tmp_path)
    resp = client.post('/api/setup', json={
        'license_accepted': True,
        'admin_username': 'boss',
        'admin_password': 'abcdefghijkl',
    }, headers={'X-CSRF-Token': 'tok'})
    assert resp.status_code == 200, resp.get_json()
    assert 'boss' in [r[1] for r in _admin_rows(app_module.config.DB_PATH)]


def test_browser_checks_use_12_characters():
    for name in ('force_change_password.html', 'setup.html'):
        text = (TEMPLATES / name).read_text(encoding='utf-8')
        assert not re.search(r'minlength="(?!12")\d+"', text), name
        assert not re.search(r'\.length < (?!12\b)\d+', text), name
        assert '.length < 12' in text, name
