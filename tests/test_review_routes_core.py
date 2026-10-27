"""Regression pins for the 2026-10-27 review of app.py and the import /
achievement / trophy route blueprints."""
import sqlite3

import pytest

import config


# ---------------------------------------------------------------------------
# routes/auth.py — the last active admin cannot be demoted or deactivated
# ---------------------------------------------------------------------------

def _stub_user_db(monkeypatch, admin_count):
    import routes.auth as auth
    writes = []

    def fake_query(sql, args=(), one=False):
        if 'COUNT(*)' in sql:
            return {'count': admin_count}
        return {'id': 7, 'username': 'solo', 'role': 'admin', 'is_active': 1}

    monkeypatch.setattr(auth, 'query', fake_query)
    monkeypatch.setattr(auth, 'execute', lambda sql, args=(): writes.append(sql))
    return writes


@pytest.mark.parametrize('body', [{'role': 'editor'}, {'is_active': False}])
def test_last_admin_cannot_be_demoted_or_deactivated(admin_test_client, monkeypatch, body):
    writes = _stub_user_db(monkeypatch, admin_count=1)
    client, csrf = admin_test_client()
    resp = client.post('/api/users/7/update', json=body, headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 403
    assert resp.get_json()['success'] is False
    assert writes == []


def test_admin_can_be_demoted_when_another_admin_remains(admin_test_client, monkeypatch):
    writes = _stub_user_db(monkeypatch, admin_count=2)
    client, csrf = admin_test_client()
    resp = client.post('/api/users/7/update', json={'role': 'editor'},
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200
    assert len(writes) == 1


def test_last_admin_can_still_be_renamed(admin_test_client, monkeypatch):
    writes = _stub_user_db(monkeypatch, admin_count=1)
    client, csrf = admin_test_client()
    resp = client.post('/api/users/7/update', json={'display_name': 'Boss', 'role': 'admin'},
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200
    assert len(writes) == 1


# ---------------------------------------------------------------------------
# routes/collector_trophies.py — batched refresh keeps the old semantics
# ---------------------------------------------------------------------------

def test_collector_trophy_refresh_batches_and_keeps_earned_at(monkeypatch):
    import app as app_module
    import routes.collector_trophies as ct

    stats = {td['stat']: 0 for td in ct.TROPHY_DEFINITIONS}
    first = ct.TROPHY_DEFINITIONS[0]
    stats[first['stat']] = first['threshold']
    monkeypatch.setattr(ct, '_gather_collection_stats', lambda user_id=None: dict(stats))

    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("DELETE FROM collector_trophies WHERE user_id = 1")
    conn.commit()
    try:
        with app_module.app.test_request_context():
            r1 = ct._refresh_trophies(user_id=1)
        earned_ids = {td['id'] for td in ct.TROPHY_DEFINITIONS
                      if stats[td['stat']] >= td['threshold']}
        assert r1['newly_earned'] == r1['total_earned'] == len(earned_ids) >= 1
        rows = dict(conn.execute(
            "SELECT id, earned_at FROM collector_trophies WHERE user_id = 1").fetchall())
        assert len(rows) == len(ct.TROPHY_DEFINITIONS)
        assert {k for k, v in rows.items() if v} == earned_ids

        # Second refresh: nothing new, earned_at untouched, total still counted.
        conn.execute("UPDATE collector_trophies SET earned_at = '2000-01-01T00:00:00Z' "
                     "WHERE user_id = 1 AND earned_at IS NOT NULL")
        conn.commit()
        with app_module.app.test_request_context():
            r2 = ct._refresh_trophies(user_id=1)
        assert r2['newly_earned'] == 0
        assert r2['total_earned'] == len(earned_ids)
        kept = {r[0] for r in conn.execute(
            "SELECT earned_at FROM collector_trophies WHERE user_id = 1 "
            "AND earned_at IS NOT NULL")}
        assert kept == {'2000-01-01T00:00:00Z'}
    finally:
        conn.execute("DELETE FROM collector_trophies WHERE user_id = 1")
        conn.commit()
        conn.close()


# ---------------------------------------------------------------------------
# app.py — the sidebar rank is read once per request
# ---------------------------------------------------------------------------

def test_collector_rank_read_once_per_request(monkeypatch):
    import app as app_module
    import routes.collector_trophies as ct
    calls = []
    monkeypatch.setattr(ct, 'get_current_rank', lambda: calls.append(1) or {'name': 'x'})
    with app_module.app.test_request_context():
        assert app_module._get_collector_rank_safe() == {'name': 'x'}
        assert app_module._get_collector_rank_safe() == {'name': 'x'}
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# routes/platform_import.py — one duplicate index per fetched library
# ---------------------------------------------------------------------------

def test_duplicate_index_matches_like_the_per_title_check(monkeypatch):
    import routes.platform_import as pi
    rows = [
        {'id': 1, 'title': 'Halo', 'system_id': 10, 'pid': None},
        {'id': 2, 'title': 'Portal', 'system_id': 20, 'pid': '400'},
        {'id': 3, 'title': 'HALO!', 'system_id': 10, 'pid': None},
        {'id': 4, 'title': 'Abzû', 'system_id': 10, 'pid': '400'},
    ]
    seen_sql = []

    def fake_query(sql, args=(), one=False):
        seen_sql.append(sql)
        return rows

    monkeypatch.setattr(pi, 'query', fake_query)
    idx = pi._DuplicateIndex('steam_app_id')
    # Platform ID wins over title, across systems; first row wins.
    assert idx.find('Something else', 10, '400') == 2
    # Normalised title, same system only; first row wins.
    assert idx.find('halo', 10, '999') == 1
    assert idx.find('halo', 20, '999') is None
    assert idx.find('Abzu', 10) == 4
    assert idx.find('', 10) is None
    assert idx.find('Halo', None) is None
    assert len(seen_sql) == 1

    with pytest.raises(ValueError):
        pi._DuplicateIndex('title; DROP TABLE games')


# ---------------------------------------------------------------------------
# routes/trophies.py — local-trophy matching reads the games once
# ---------------------------------------------------------------------------

def test_find_matching_game_with_candidates_skips_the_query(monkeypatch):
    import routes.trophies as tr
    rows = [
        {'id': 1, 'title': 'Journey', 'folder': 'ps4'},
        {'id': 2, 'title': 'Journey', 'folder': 'ps3'},
        {'id': 3, 'title': 'Uncharted 2: Among Thieves', 'folder': 'ps3'},
    ]
    calls = []
    monkeypatch.setattr(tr, 'query', lambda *a, **k: calls.append(a) or rows)
    candidates = tr._ps_match_candidates()
    assert len(calls) == 1

    # PS3 exact match beats an earlier exact match on another system.
    assert tr.find_matching_game('Journey', candidates)['id'] == 2
    # Substring pass.
    assert tr.find_matching_game('Uncharted 2', candidates)['id'] == 3
    assert tr.find_matching_game('Nothing Like It', candidates) is None
    assert len(calls) == 1
    # Without candidates it still reads them itself.
    assert tr.find_matching_game('Journey')['id'] == 2
    assert len(calls) == 2


def test_psn_games_api_clamps_paging(admin_test_client):
    client, _csrf = admin_test_client()
    resp = client.get('/api/psn/games?per_page=0&page=-3')
    assert resp.status_code == 200
    body = resp.get_json()
    assert body['per_page'] == 1 and body['page'] == 1
