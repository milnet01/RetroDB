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
