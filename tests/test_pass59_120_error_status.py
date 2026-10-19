"""PASS-59-120: the last error(..., code=200) replies answer 4xx/5xx.

One or more failure paths per converted file, as in
test_pass59_114_error_status.py. Each must answer with the status below AND
the standard envelope ({success: false, error: str}). No network call is made.
"""
import os
import sqlite3

import pytest

MISSING = 987654321  # an id no test database holds


@pytest.fixture
def admin_row():
    """The stub admin (id 1) as a real users row, with a password set."""
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                 "VALUES (1, 'admin-stub', 'x', 'admin')")
    conn.commit()
    conn.close()


CASES = [
    # (label, method, url, json body, expected status)
    ('auth: login without a user', 'post', '/api/login', {}, 400),
    ('auth: login as a missing user', 'post', '/api/login', {'user_id': MISSING}, 404),
    ('auth: create a user without a name', 'post', '/api/users/create', {}, 400),
    ('auth: create a user with an invalid role', 'post', '/api/users/create',
     {'username': 'p59120', 'role': 'emperor'}, 422),
    ('auth: update a missing user', 'post', f'/api/users/{MISSING}/update', {}, 404),
    ('auth: delete a missing user', 'post', f'/api/users/{MISSING}/delete', {}, 404),
    ('auth: save an unknown locale', 'post', '/api/users/settings',
     {'locale_preference': 'qq_GONE'}, 422),
    ('auth: save an unknown theme', 'post', '/api/users/settings',
     {'theme_preference': 'no-such-theme'}, 422),
    ('auth: change password with none given', 'post', '/api/profile/password', {}, 400),
    ('auth: upload an avatar with no file', 'post', '/api/users/avatar', None, 400),
    ('achievements: progress for a game never synced', 'get',
     f'/api/achievements/{MISSING}', None, 404),
    ('achievements: sync a missing system', 'post',
     f'/api/achievements/sync-system/{MISSING}', None, 404),
    ('achievements: refresh a missing game', 'post',
     f'/api/achievements/refresh/{MISSING}', None, 404),
    ('bulk_scrape: legacy scrape without a game', 'post', '/api/bulk-scrape', {}, 400),
    ('bulk_scrape: job start with no games', 'post', '/api/bulk-scrape-job/start', {}, 400),
    ('clz_import: parse with no file', 'post', '/api/clz-import/parse', None, 400),
    ('clz_import: import with no games', 'post', '/api/clz-import/import', {}, 400),
    ('games_media: delete a screenshot without naming one', 'post',
     f'/api/delete-screenshot/{MISSING}', {}, 400),
    ('hltb: search with no query', 'post', '/api/hltb/search', {}, 400),
]


@pytest.mark.parametrize('label,method,url,body,status', CASES, ids=[c[0] for c in CASES])
def test_failure_answers_with_an_error_status(admin_test_client, label, method, url, body,
                                              status):
    client, csrf = admin_test_client()
    kw = {'headers': {'X-CSRF-Token': csrf}}
    if body is not None:
        kw['json'] = body
    resp = getattr(client, method)(url, **kw)
    data = resp.get_json()
    assert isinstance(data, dict) and isinstance(data.get('error'), str), label
    assert (resp.status_code, data['success']) == (status, False), label


def test_login_without_a_password_is_a_401_that_asks_for_one(admin_row, admin_test_client):
    client, csrf = admin_test_client()
    resp = client.post('/api/login', json={'user_id': 1},
                       headers={'X-CSRF-Token': csrf})
    data = resp.get_json()
    assert (resp.status_code, data['success'], data.get('needs_password')) == \
        (401, False, True)


def test_deleting_your_own_account_is_a_403(admin_row, admin_test_client):
    client, csrf = admin_test_client()
    resp = client.post('/api/users/1/delete', headers={'X-CSRF-Token': csrf})
    assert (resp.status_code, resp.get_json()['success']) == (403, False)


def test_hltb_no_match_is_a_404(admin_test_client, monkeypatch):
    import scraper.hltb_lookup as hltb_lookup
    monkeypatch.setattr(hltb_lookup, 'lookup_playtime', lambda *a, **k: None)
    client, csrf = admin_test_client()
    resp = client.post('/api/hltb/search', json={'query': 'Nothing Like This'},
                       headers={'X-CSRF-Token': csrf})
    assert (resp.status_code, resp.get_json()['success']) == (404, False)


def test_ai_fill_with_no_data_is_a_502(admin_test_client, monkeypatch):
    import routes.games_ai as games_ai
    import scraper.scrape_ai as scrape_ai
    import scraper.hybrid_scraper as hybrid_scraper
    monkeypatch.setattr(games_ai, 'query', lambda *a, **k: {
        'id': 1, 'title': 'Quiet Game', 'system_id': 1, 'system_folder': 'snes',
        'system_name': 'SNES', 'rom_path': '/roms/snes/q.zip'})
    monkeypatch.setattr(hybrid_scraper, 'get_system_default_controller_name',
                        lambda *a, **k: None)
    monkeypatch.setattr(scrape_ai, 'get_game_details', lambda *a, **k: None)
    client, csrf = admin_test_client()
    resp = client.post('/api/game/1/ai-fill', headers={'X-CSRF-Token': csrf})
    assert (resp.status_code, resp.get_json()['success']) == (502, False), \
        resp.get_data(as_text=True)[:300]
