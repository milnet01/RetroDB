"""PASS-59-114: a failed request answers with a 4xx/5xx status, not HTTP 200.

One or more failure paths per converted route file. Each must answer with
the status below AND the standard envelope ({success: false, error: str}),
so a caller can rely on either. No network call is made.
"""
import pytest

MISSING = 987654321  # an id no test database holds


def _post(client, csrf, url, **kw):
    return client.post(url, headers={'X-CSRF-Token': csrf}, **kw)


CASES = [
    # (label, method, url, json body, expected status)
    ('bonus_discs: link without ids', 'post', '/api/bonus-discs/link', {}, 400),
    ('bonus_discs: link to missing games', 'post', '/api/bonus-discs/link',
     {'bonus_id': MISSING, 'parent_id': MISSING + 1}, 404),
    ('bonus_discs: parents of a missing game', 'get',
     f'/api/bonus-discs/potential-parents/{MISSING}', None, 404),
    ('bonus_discs: mark without game_id', 'post', '/api/bonus-discs/mark', {}, 400),
    ('games: invalid completion status', 'post', f'/api/game/{MISSING}/completion',
     {'status': 'not-a-status'}, 400),
    ('scraper: allowance for an unknown scraper', 'get',
     '/api/scraper-allowance/no-such-scraper', None, 404),
    ('scrape_logs: delete a missing log', 'delete',
     '/api/logs/delete/scraping_59114_missing.log', None, 404),
    ('scrape_logs: view a missing log', 'get',
     '/api/logs/view/scraping_59114_missing.log', None, 404),
    ('settings: restore a missing backup', 'post',
     '/api/restore/roms_59114_missing.db', None, 404),
    ('platform_import: Steam import with nothing selected', 'post',
     '/api/steam/import', {}, 400),
    ('platform_import: Xbox import with nothing selected', 'post',
     '/api/xbox/import', {}, 400),
    ('trophies: link a PSN game without npwr_id', 'post', '/api/psn/link-game', {}, 400),
    ('trophies: rename a trophy group without ids', 'post',
     '/api/psn/edit-group-name', {}, 400),
    ('trophies: save NPSSO with none given', 'post', '/api/psn/save-npsso', {}, 400),
    ('trophies: bulk refresh with nothing selected', 'post',
     '/api/psn/bulk-refresh/start', {}, 400),
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


def test_systems_list_failure_is_a_500(admin_test_client, monkeypatch):
    import routes.systems as systems

    def boom(*a, **k):
        raise RuntimeError('db down')

    monkeypatch.setattr(systems, 'query', boom)
    client, _csrf = admin_test_client()
    resp = client.get('/api/systems')
    assert (resp.status_code, resp.get_json()['success']) == (500, False)


def test_steam_single_sync_without_credentials_is_a_400(admin_test_client, monkeypatch):
    import services.jobs.platform_sync as platform_sync
    monkeypatch.setattr(platform_sync, '_get_steam_credentials', lambda **k: ('', ''))
    client, csrf = admin_test_client()
    resp = _post(client, csrf, f'/api/steam-achievements/sync/{MISSING}')
    assert (resp.status_code, resp.get_json()['success']) == (400, False)


def test_xbox_single_sync_without_credentials_is_a_400(admin_test_client, monkeypatch):
    import routes.scraper as scraper
    monkeypatch.setattr(scraper, 'get_saved_api_keys', lambda: {})
    client, csrf = admin_test_client()
    resp = _post(client, csrf, f'/api/xbox-achievements/sync/{MISSING}')
    assert (resp.status_code, resp.get_json()['success']) == (400, False)


def test_npsso_failure_does_not_echo_the_exception(admin_test_client, monkeypatch):
    """The reply no longer carries the raw exception text."""
    from types import SimpleNamespace
    import routes.trophies as trophies

    def boom():
        raise RuntimeError('secret-internal-detail-59114')

    # Sign-in succeeds; the first call on the client fails.
    monkeypatch.setattr(trophies, 'create_psn_client',
                        lambda *a, **k: (SimpleNamespace(me=boom), None))
    client, csrf = admin_test_client()
    resp = _post(client, csrf, '/api/psn/save-npsso', json={'npsso': 'x' * 64})
    data = resp.get_json()
    assert data['success'] is False
    assert 'secret-internal-detail-59114' not in data['error']
    assert resp.status_code == 502
