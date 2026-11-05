"""PASS-59-248: sign-in hardening (audit 2026-11-04).

- A password change or an admin reset signs the account out everywhere else.
- A rejected avatar upload keeps the old picture.
- The setup wizard's API needs the CSRF token like every other POST.
- A non-text value in a sign-in field gets a 400, not a 500.
- A secret key that cannot be saved is logged.
"""

import logging
import os
import sqlite3

import pytest

import config

PASSWORD = 'correct-horse-battery'


def _make_user(name, role='admin', password=PASSWORD):
    from services.auth import hash_password
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cur = conn.execute(
            "INSERT INTO users (username, password_hash, role, is_active) VALUES (?, ?, ?, 1)",
            (name, hash_password(password), role))
        conn.execute("INSERT INTO user_settings (user_id) VALUES (?)", (cur.lastrowid,))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _signed_in_client(uid, addr):
    """A real sign-in through /api/login; returns (client, csrf token)."""
    import app as app_module
    client = app_module.app.test_client()
    r = client.post('/api/login', json={'user_id': uid, 'password': PASSWORD},
                    environ_base={'REMOTE_ADDR': addr})
    assert r.status_code == 200, r.get_json()
    return client, r.get_json()['csrf_token']


def _is_signed_in(client):
    """/api/users is admin-only: 200 when the cookie still holds a valid sign-in."""
    return client.get('/api/users').status_code == 200


# ---------------------------------------------------------------------------
# Session epoch
# ---------------------------------------------------------------------------

def test_password_change_signs_out_other_sessions(setup_complete, monkeypatch):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    uid = _make_user('pass59248-own')
    phone, csrf = _signed_in_client(uid, '10.59.248.1')
    laptop, _ = _signed_in_client(uid, '10.59.248.2')
    assert _is_signed_in(phone) and _is_signed_in(laptop)

    r = phone.post('/api/profile/password', headers={'X-CSRF-Token': csrf},
                   json={'current_password': PASSWORD, 'new_password': 'a-brand-new-password'})
    assert r.status_code == 200, r.get_json()

    assert _is_signed_in(phone), 'the session that changed the password stays signed in'
    assert not _is_signed_in(laptop), 'the other session must be signed out'


def test_admin_reset_signs_the_user_out(setup_complete, monkeypatch):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    admin_uid = _make_user('pass59248-admin')
    member_uid = _make_user('pass59248-member')
    admin, csrf = _signed_in_client(admin_uid, '10.59.248.3')
    member, _ = _signed_in_client(member_uid, '10.59.248.4')
    assert _is_signed_in(member)

    r = admin.post(f'/api/users/{member_uid}/update', headers={'X-CSRF-Token': csrf},
                   # Skip the forced change: it blocks the old session on its own
                   # and would hide whether the reset signed it out.
                   json={'new_password': 'reset-by-the-admin', 'skip_force_change': True})
    assert r.status_code == 200, r.get_json()

    assert not _is_signed_in(member)
    assert _is_signed_in(admin)


# ---------------------------------------------------------------------------
# Avatar
# ---------------------------------------------------------------------------

def test_rejected_avatar_keeps_the_old_one(admin_test_client):
    import io
    client, csrf = admin_test_client(user={'id': 924801, 'username': 'av', 'role': 'admin'})
    avatars = os.path.join(config.IMAGE_PATH, 'avatars')
    os.makedirs(avatars, exist_ok=True)
    old = os.path.join(avatars, 'user_924801_avatar.png')
    with open(old, 'wb') as f:
        f.write(b'old picture')
    try:
        r = client.post('/api/users/avatar', headers={'X-CSRF-Token': csrf},
                        data={'avatar': (io.BytesIO(b'not an image'), 'new.jpg')},
                        content_type='multipart/form-data')
        assert r.status_code == 422
        assert os.path.isfile(old), 'a rejected upload deleted the old avatar'
    finally:
        for ext in ('png', 'jpg'):
            p = os.path.join(avatars, f'user_924801_avatar.{ext}')
            if os.path.isfile(p):
                os.remove(p)


def test_accepted_avatar_replaces_the_old_one(admin_test_client):
    import io
    from PIL import Image
    client, csrf = admin_test_client(user={'id': 924802, 'username': 'av2', 'role': 'admin'})
    avatars = os.path.join(config.IMAGE_PATH, 'avatars')
    os.makedirs(avatars, exist_ok=True)
    old = os.path.join(avatars, 'user_924802_avatar.png')
    with open(old, 'wb') as f:
        f.write(b'old picture')
    buf = io.BytesIO()
    Image.new('RGB', (4, 4), 'red').save(buf, 'JPEG')
    buf.seek(0)
    try:
        r = client.post('/api/users/avatar', headers={'X-CSRF-Token': csrf},
                        data={'avatar': (buf, 'new.jpg')}, content_type='multipart/form-data')
        assert r.status_code == 200, r.get_json()
        assert not os.path.isfile(old)
        assert os.path.isfile(os.path.join(avatars, 'user_924802_avatar.jpg'))
    finally:
        for ext in ('png', 'jpg'):
            p = os.path.join(avatars, f'user_924802_avatar.{ext}')
            if os.path.isfile(p):
                os.remove(p)


# ---------------------------------------------------------------------------
# Setup CSRF
# ---------------------------------------------------------------------------

@pytest.fixture
def setup_not_done(monkeypatch):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    monkeypatch.setattr('app.settings_manager.load_settings', lambda: {})
    monkeypatch.setattr(config, 'ROM_PATH', '', raising=False)
    return app_module.app.test_client()


@pytest.mark.parametrize('path', ['/api/setup', '/api/setup/browse-folders'])
def test_setup_api_needs_the_csrf_token(setup_not_done, path):
    client = setup_not_done
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'setup-token'
    assert client.post(path, json={}).status_code == 403
    # With the token the request reaches the route (an empty body is refused there).
    r = client.post(path, json={}, headers={'X-CSRF-Token': 'setup-token'})
    assert r.status_code != 403, r.get_json()


# ---------------------------------------------------------------------------
# Non-text input
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('body', [
    {'user_id': 1, 'password': 12345678901234},
    {'user_id': [1], 'password': 'x'},
    {'user_id': {'a': 1}, 'password': 'x'},
])
def test_login_rejects_non_text_fields(setup_complete, monkeypatch, body):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    uid = _make_user(f'pass59248-types-{len(str(body))}')
    if body['user_id'] == 1:
        body = dict(body, user_id=uid)
    r = app_module.app.test_client().post('/api/login', json=body,
                                          environ_base={'REMOTE_ADDR': '10.59.248.9'})
    assert r.status_code == 400, (r.status_code, r.get_json())
    assert r.get_json()['success'] is False


def test_login_rejects_a_json_list_body(setup_complete, monkeypatch):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    r = app_module.app.test_client().post('/api/login', json=[1, 2],
                                          environ_base={'REMOTE_ADDR': '10.59.248.10'})
    assert r.status_code == 400, (r.status_code, r.get_json())


@pytest.mark.parametrize('path, body', [
    ('/api/profile/password', {'current_password': 5, 'new_password': 'long-enough-password'}),
    ('/api/profile/password', {'current_password': PASSWORD, 'new_password': 123456789012345}),
    ('/api/users/create', {'username': ['x'], 'password': 'long-enough-password'}),
    ('/api/users/create', {'username': 'pass59248-x', 'password': 123456789012345}),
])
def test_auth_routes_reject_non_text_fields(setup_complete, monkeypatch, path, body):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    uid = _make_user(f'pass59248-route-{abs(hash((path, str(body))))}')
    client, csrf = _signed_in_client(uid, '10.59.248.11')
    r = client.post(path, json=body, headers={'X-CSRF-Token': csrf})
    assert r.status_code == 400, (r.status_code, r.get_json())


def test_admin_update_rejects_a_non_text_password(setup_complete, monkeypatch):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    admin_uid = _make_user('pass59248-upd-admin')
    member_uid = _make_user('pass59248-upd-member')
    client, csrf = _signed_in_client(admin_uid, '10.59.248.12')
    r = client.post(f'/api/users/{member_uid}/update', headers={'X-CSRF-Token': csrf},
                    json={'new_password': 123456789012345})
    assert r.status_code == 400, (r.status_code, r.get_json())


def test_setup_rejects_non_text_admin_fields(setup_not_done):
    client = setup_not_done
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'setup-token'
    r = client.post('/api/setup', headers={'X-CSRF-Token': 'setup-token'},
                    json={'license_accepted': True, 'admin_username': 5,
                          'admin_password': 'long-enough-password'})
    assert r.status_code == 400, (r.status_code, r.get_json())


# ---------------------------------------------------------------------------
# Secret key
# ---------------------------------------------------------------------------

def test_unsaved_secret_key_is_logged(monkeypatch, caplog, tmp_path):
    import app as app_module
    monkeypatch.delenv('RETRODB_SECRET_KEY', raising=False)
    monkeypatch.setattr(config, 'BASE_DIR', str(tmp_path))

    def _refuse(*_a, **_k):
        raise OSError('read-only')
    monkeypatch.setattr('services.atomic_io.atomic_write_text', _refuse)
    with caplog.at_level(logging.WARNING):
        key = app_module._get_secret_key()
    assert key
    assert any('secret key' in rec.getMessage().lower() for rec in caplog.records), \
        [r.getMessage() for r in caplog.records]


def test_setup_page_hands_out_the_token_its_api_needs(setup_not_done):
    """A fresh install: the page's own meta token unlocks the setup API.

    base.html's fetch wrapper copies `<meta name="csrf-token">` into the
    X-CSRF-Token header, so this is the browser's path without the browser.
    """
    import re
    client = setup_not_done
    page = client.get('/setup')
    assert page.status_code == 200
    token = re.search(r'<meta name="csrf-token" content="([0-9a-f]+)">',
                      page.get_data(as_text=True)).group(1)
    r = client.post('/api/setup/browse-folders', json={}, headers={'X-CSRF-Token': token})
    assert r.status_code == 200, r.get_json()
