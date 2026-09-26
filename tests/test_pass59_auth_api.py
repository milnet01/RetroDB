"""Pass 59.45, 59.73, 59.74, 59.77: API callers get the answer they can read.

59.45 — `@handle_api_errors` caught `HTTPException`, so a client's 4xx (a
malformed JSON body, an oversized upload, an `abort(403)`) became a 500.

59.73 — `_rate_limit()` discarded the wrapper `limiter.limit()` returned, so
no per-route limit was enforced, the login limit included.

59.74 — the login guard sent `next` as an absolute URL, which the login
handler's open-redirect check always rejects.

59.77 — a user flagged for a forced password change got the HTML change
form with a 200 from every `/api/*` endpoint.
"""
from urllib.parse import parse_qs, urlparse

import pytest
from flask import abort

_CSRF = 'tok'
HEADERS = {'X-CSRF-Token': _CSRF}


# ---------------------------------------------------------------------------
# 59.45
# ---------------------------------------------------------------------------

def test_handle_api_errors_lets_http_exceptions_through():
    from werkzeug.exceptions import BadRequest, Forbidden
    from services.api_helpers import handle_api_errors

    @handle_api_errors
    def view_400():
        raise BadRequest()

    @handle_api_errors
    def view_403():
        abort(403)

    import app as app_module
    with app_module.app.test_request_context('/api/x'):
        with pytest.raises(BadRequest):
            view_400()
        with pytest.raises(Forbidden):
            view_403()


def test_handle_api_errors_still_masks_unexpected_errors():
    import app as app_module
    from services.api_helpers import handle_api_errors

    @handle_api_errors
    def view_boom():
        raise RuntimeError('boom')

    with app_module.app.test_request_context('/api/x'):
        resp, status = view_boom()
    assert status == 500


# ---------------------------------------------------------------------------
# 59.73
# ---------------------------------------------------------------------------

def test_login_rate_limit_is_enforced_with_a_json_429(setup_complete):
    import app as app_module
    if not app_module.limiter:
        pytest.skip('flask-limiter not installed')
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = _CSRF
    addr = {'REMOTE_ADDR': '10.59.73.1'}
    try:
        statuses = [client.post('/api/login', json={}, headers=HEADERS,
                                environ_base=addr).status_code
                    for _ in range(11)]
        last = client.post('/api/login', json={}, headers=HEADERS, environ_base=addr)
        assert 429 in statuses + [last.status_code], statuses
        assert last.status_code == 429
        body = last.get_json()
        assert body is not None and body['success'] is False
    finally:
        app_module.limiter.reset()


# ---------------------------------------------------------------------------
# 59.74
# ---------------------------------------------------------------------------

def test_login_guard_sends_a_path_not_a_url(setup_complete):
    import app as app_module
    client = app_module.app.test_client()
    resp = client.get('/games?system=snes')
    assert resp.status_code == 302
    nxt = parse_qs(urlparse(resp.headers['Location']).query)['next'][0]
    parsed = urlparse(nxt)
    assert not parsed.scheme and not parsed.netloc, nxt
    assert nxt == '/games?system=snes'


# ---------------------------------------------------------------------------
# 59.77
# ---------------------------------------------------------------------------

def test_forced_password_change_answers_api_with_json(monkeypatch, setup_complete):
    import app as app_module
    user = {'id': 1, 'username': 'admin', 'role': 'admin', 'force_password_change': 1}
    monkeypatch.setattr('app.get_current_user', lambda: user)
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    client = app_module.app.test_client()
    resp = client.get('/api/games')
    assert resp.status_code >= 400
    body = resp.get_json()
    assert body is not None and body['success'] is False


def test_forced_password_change_still_renders_the_form_for_pages(monkeypatch, setup_complete):
    import app as app_module
    user = {'id': 1, 'username': 'admin', 'role': 'admin', 'force_password_change': 1}
    monkeypatch.setattr('app.get_current_user', lambda: user)
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    client = app_module.app.test_client()
    resp = client.get('/games')
    assert resp.status_code == 200
    assert b'<form' in resp.data or b'password' in resp.data.lower()


def test_malformed_json_body_is_a_400_envelope(monkeypatch, setup_complete):
    """The finding's own verify step: a bare request.get_json() on a bad body."""
    import app as app_module
    user = {'id': 1, 'username': 'admin', 'role': 'admin'}
    monkeypatch.setattr('app.get_current_user', lambda: user)
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = _CSRF
    resp = client.post('/api/reports/rename-rom', data='{not json',
                       content_type='application/json', headers=HEADERS)
    assert resp.status_code == 400
    body = resp.get_json()
    assert body is not None and body['success'] is False


# ---------------------------------------------------------------------------
# 59.75
# ---------------------------------------------------------------------------

def test_bulk_scrape_status_keeps_the_envelope_success_flag(monkeypatch, setup_complete):
    """A job with no successes yet answered `success: 0`, which every caller
    reads as a failed request."""
    import app as app_module
    user = {'id': 1, 'username': 'admin', 'role': 'admin'}
    monkeypatch.setattr('app.get_current_user', lambda: user)
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    body = app_module.app.test_client().get('/api/bulk-scrape-job/status').get_json()
    assert body['success'] is True
    assert body['success_count'] == 0


# ---------------------------------------------------------------------------
# 59.76
# ---------------------------------------------------------------------------

def _owned_tables():
    """Every table with a per-user column, read from the live schema."""
    from services.database import query
    tables = [r['name'] for r in query(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")]
    owned = []
    for t in tables:
        cols = {r['name'] for r in query(f"SELECT name FROM pragma_table_info('{t}')")}
        owned += [(t, c) for c in ('user_id', 'owner_id') if c in cols]
    return owned


def test_deleting_a_user_removes_every_row_they_own(monkeypatch, setup_complete):
    import uuid
    import app as app_module
    from services.database import execute, query
    from tests._util import delete_rows

    admin = {'id': 1, 'username': 'admin', 'role': 'admin'}
    monkeypatch.setattr('app.get_current_user', lambda: admin)
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})

    uid = execute("INSERT INTO users (username, role) VALUES (?, 'viewer')",
                  (f'pass5976-{uuid.uuid4().hex}',))
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                     ('Pass59 Users', f'pass5976-{uuid.uuid4().hex}'))
    game_id = execute("INSERT INTO games (system_id, title, rom_path) VALUES (?, ?, ?)",
                      (sys_id, 'Owned Game', f'pass5976/{uuid.uuid4().hex}.zip'))
    try:
        execute("INSERT INTO user_settings (user_id) VALUES (?)", (uid,))
        tag = execute("INSERT INTO tags (name, owner_id) VALUES ('mine', ?)", (uid,))
        execute("INSERT INTO game_tags (game_id, tag_id) VALUES (?, ?)", (game_id, tag))
        lst = execute("INSERT INTO lists (name, owner_id) VALUES ('mine', ?)", (uid,))
        execute("INSERT INTO list_games (list_id, game_id, position) VALUES (?, ?, 1)", (lst, game_id))
        execute("INSERT INTO wishlist (title, owner_id) VALUES ('mine', ?)", (uid,))
        execute("INSERT INTO user_platform_tokens (user_id, platform, tokens) VALUES (?, 'psn', '{}')", (uid,))
        pg = execute("INSERT INTO psn_games (npwr_id, user_id) VALUES (?, ?)", (f'NPWR{uid}', uid))
        execute("INSERT INTO psn_trophies (psn_game_id, user_id) VALUES (?, ?)", (pg, uid))
        execute("INSERT INTO user_game_views (user_id, game_id, last_viewed) VALUES (?, ?, 'now')",
                (uid, game_id))

        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['_csrf_token'] = _CSRF
        resp = client.post(f'/api/users/{uid}/delete', headers=HEADERS)
        body = resp.get_json()
        assert body['success'] is True, body

        assert query("SELECT 1 FROM users WHERE id = ?", (uid,), one=True) is None
        left = [(t, c) for t, c in _owned_tables()
                if query(f"SELECT 1 FROM {t} WHERE {c} = ?", (uid,), one=True)]
        assert not left, f"rows left behind: {left}"
        assert query("SELECT 1 FROM psn_trophies WHERE psn_game_id = ?", (pg,), one=True) is None
    finally:
        # psn_trophies references psn_games, so it goes first.
        for t, c in sorted(_owned_tables(), key=lambda tc: tc[0] != 'psn_trophies'):
            execute(f"DELETE FROM {t} WHERE {c} = ?", (uid,))
        execute("DELETE FROM users WHERE id = ?", (uid,))
        delete_rows(('games', game_id), ('systems', sys_id))
