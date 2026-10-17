"""PASS-59-118: smaller trophy defects found while writing the trophies spec.

No network call is made: RA replies are built by hand.
"""
import os
import sqlite3

import pytest

from tests.test_pass59_trophy_dataloss import ra_db  # noqa: F401 — fixture


def _ra_progress(conn, game_id):
    return conn.execute("SELECT earned_achievements, total_achievements, source "
                        "FROM game_achievement_progress WHERE game_id = ? AND user_id = 1",
                        (game_id,)).fetchone()


def test_ra_single_game_sync_stores_the_total(ra_db, admin_test_client, monkeypatch):  # noqa: F811
    conn, _sys_id, ids = ra_db
    import routes.achievements as achievements
    import scraper.retroachievements as ra
    monkeypatch.setattr(achievements, 'get_user_ra_credentials', lambda: ('user', 'key'))
    # The keys get_user_game_progress_custom really returns.
    monkeypatch.setattr(ra, 'get_user_game_progress_custom', lambda *a: {
        'achievement_count': 12, 'unlocked_count': 3, 'total_points': 100,
        'earned_points': 25, 'completion_percentage': 25.0})
    client, csrf = admin_test_client()
    resp = client.post(f"/api/achievements/sync/{ids['ra']}", headers={'X-CSRF-Token': csrf})
    assert resp.get_json()['success'] is True
    row = _ra_progress(conn, ids['ra'])
    assert (row['earned_achievements'], row['total_achievements']) == (3, 12)


@pytest.fixture
def own_ra_account(ra_db):  # noqa: F811
    conn = ra_db[0]
    conn.execute("INSERT OR IGNORE INTO user_settings (user_id) VALUES (1)")
    conn.execute("UPDATE user_settings SET ra_username = 'mine', ra_api_key = 'k-mine' "
                 "WHERE user_id = 1")
    conn.commit()
    yield ra_db
    conn.execute("UPDATE user_settings SET ra_username = NULL, ra_api_key = NULL "
                 "WHERE user_id = 1")
    conn.commit()


def test_ra_sync_job_uses_the_callers_ra_account(own_ra_account, monkeypatch):
    from types import SimpleNamespace
    import requests
    import scraper.scraper_manager as scraper_manager
    import services.jobs.ra_sync as ra_sync
    _conn, sys_id, _ids = own_ra_account
    monkeypatch.setattr(scraper_manager, 'get_api_key',
                        lambda key, env: {'ra_apikey': 'k-global', 'ra_username': 'global'}[key])
    seen = []

    def get(url, params=None, **k):
        seen.append(params.get('u'))
        return SimpleNamespace(status_code=503, json=lambda: {})

    monkeypatch.setattr(requests, 'get', get)
    monkeypatch.setattr(ra_sync, 'shutdown_requested', SimpleNamespace(wait=lambda s: None),
                        raising=False)
    job = ra_sync.RASyncJob()
    job.system_id, job._user_id, job.running = sys_id, 1, True
    job._run_sync()
    assert seen and set(seen) == {'mine'}


def test_dashboard_achievement_totals_are_the_callers(ra_db):  # noqa: F811
    import app as app_module
    from flask import g
    conn, _sys_id, ids = ra_db
    conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                 "VALUES (2, 'other-stub', 'x', 'user')")
    conn.execute("UPDATE game_achievement_progress SET earned_achievements = 5, "
                 "total_achievements = 10 WHERE game_id = ? AND user_id = 1", (ids['ra'],))
    conn.execute("INSERT INTO game_achievement_progress (game_id, user_id, source, "
                 "earned_achievements, total_achievements) VALUES (?, 2, 'ra', 100, 200)",
                 (ids['ra'],))
    conn.commit()
    try:
        with app_module.app.test_request_context('/dashboard'):
            g.user = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}
            stats = app_module.get_stats()
        mine = conn.execute("SELECT SUM(earned_achievements) e, SUM(total_achievements) t "
                            "FROM game_achievement_progress WHERE user_id = 1").fetchone()
        assert (stats['total_earned_achievements'], stats['total_available_achievements']) \
            == (mine['e'], mine['t'])
    finally:
        conn.execute("DELETE FROM game_achievement_progress WHERE game_id = ? AND user_id = 2",
                     (ids['ra'],))
        conn.commit()


@pytest.mark.parametrize('job_type,params,role,allowed', [
    ('ra_refresh', {'system_id': None}, 'editor', False),      # admin-only job
    ('ra_refresh', {'system_id': None}, 'admin', True),
    ('steam_sync', {'user_id': 1}, 'player', False),           # editor job
    ('psn_refresh', {'user_id': 1}, 'player', False),          # someone else's job
    ('psn_refresh', {'user_id': 2}, 'player', True),           # the caller's own
])
def test_resume_job_needs_the_starting_routes_rights(admin_test_client, monkeypatch,
                                                     job_type, params, role, allowed):
    import services.jobs as jobs
    import services.jobs.base as base
    monkeypatch.setattr(base, 'get_recoverable_jobs', lambda: [
        {'id': 59118, 'job_type': job_type, 'params': params, 'progress': None}])
    monkeypatch.setattr(base, 'persist_job_complete', lambda *a, **k: None)
    calls = []
    handler = getattr(jobs, f'{job_type}_job')
    monkeypatch.setattr(handler, 'resume_from_params',
                        lambda p, progress=None: calls.append(p) or True)
    client, csrf = admin_test_client(user={'id': 2, 'username': 'u-stub', 'role': role})
    resp = client.post('/api/jobs/resume/59118', headers={'X-CSRF-Token': csrf})
    assert (resp.status_code == 200, bool(calls)) == (allowed, allowed)
    if not allowed:
        assert resp.status_code == 403


@pytest.mark.parametrize('job_name,owner_attr,url', [
    ('ra_sync_job', '_user_id', '/api/achievements/sync-cancel'),
    ('steam_sync_job', '_user_id', '/api/steam/cancel-sync'),
    ('xbox_sync_job', 'user_id', '/api/xbox/cancel-sync'),
])
@pytest.mark.parametrize('caller,allowed', [
    ({'id': 2, 'username': 'e-stub', 'role': 'editor'}, False),   # another editor
    ({'id': 3, 'username': 'o-stub', 'role': 'editor'}, True),    # the owner
    ({'id': 1, 'username': 'admin-stub', 'role': 'admin'}, True),
])
def test_only_the_owner_or_an_admin_cancels_a_sync(admin_test_client, monkeypatch,
                                                   job_name, owner_attr, url, caller, allowed):
    import services.jobs as jobs
    job = getattr(jobs, job_name)
    monkeypatch.setattr(job, 'running', True)
    monkeypatch.setattr(job, 'completed', False)
    monkeypatch.setattr(job, 'cancelled', False)
    monkeypatch.setattr(job, owner_attr, 3)
    client, csrf = admin_test_client(user=caller)
    body = client.post(url, headers={'X-CSRF-Token': csrf}).get_json()
    assert isinstance(body['success'], bool)
    assert (body['success'], job.cancelled) == (allowed, allowed)


@pytest.mark.parametrize('path,saved', [
    ('relative/trophies', False),
    ('/', False),
    ('/no/such/folder/59118', False),
    ('', True),
])
def test_user_rpcs3_path_is_validated(own_ra_account, admin_test_client, path, saved):
    conn = own_ra_account[0]
    conn.execute("UPDATE user_settings SET rpcs3_trophy_path = 'sentinel' WHERE user_id = 1")
    conn.commit()
    client, csrf = admin_test_client()
    body = client.post('/api/users/settings', json={'rpcs3_trophy_path': path},
                       headers={'X-CSRF-Token': csrf}).get_json()
    stored = conn.execute("SELECT rpcs3_trophy_path FROM user_settings WHERE user_id = 1"
                          ).fetchone()[0]
    assert isinstance(body['success'], bool)
    assert (body['success'], stored) == ((True, path) if saved else (False, 'sentinel'))


def test_user_rpcs3_path_stores_the_canonical_folder(own_ra_account, admin_test_client, tmp_path):
    conn = own_ra_account[0]
    client, csrf = admin_test_client()
    client.post('/api/users/settings', json={'rpcs3_trophy_path': f'{tmp_path}/'},
                headers={'X-CSRF-Token': csrf})
    stored = conn.execute("SELECT rpcs3_trophy_path FROM user_settings WHERE user_id = 1"
                          ).fetchone()[0]
    assert stored == os.path.realpath(tmp_path)


def test_psn_bulk_refresh_signs_in_as_its_owner(monkeypatch):
    import app  # noqa: F401 — builds the throwaway schema
    import routes.trophies as trophies
    from services.jobs.psn_refresh import PSNRefreshJob
    seen = []

    def fake_client(npsso, user_id=None, **k):
        seen.append(user_id)
        return None, 'stop here'

    monkeypatch.setattr(trophies, 'create_psn_client', fake_client)
    job = PSNRefreshJob()
    job.npwr_ids, job._npsso, job._user_id, job.running = ['NPWR59118_00'], 'npsso', 7, True
    job.return_url = None
    job._run_refresh()
    assert seen == [7]


def test_collector_stats_count_a_steam_earn_once(ra_db):  # noqa: F811
    import app as app_module
    from routes.collector_trophies import _gather_collection_stats
    conn, _sys_id, ids = ra_db

    def earned():
        with app_module.app.app_context():
            return _gather_collection_stats(user_id=1)['total_achievements_earned']

    before = earned()
    # A Steam sync writes both: the per-game progress row and one row per achievement.
    conn.execute("UPDATE game_achievement_progress SET earned_achievements = 4, "
                 "total_achievements = 10 WHERE game_id = ? AND user_id = 1", (ids['steam'],))
    for n in range(4):
        conn.execute("INSERT INTO steam_achievements (game_id, user_id, apiname, name, achieved) "
                     "VALUES (?, 1, ?, ?, 1)", (ids['steam'], f'a{n}', f'A{n}'))
    conn.commit()
    try:
        assert earned() - before == 4
    finally:
        conn.execute("DELETE FROM steam_achievements WHERE game_id = ?", (ids['steam'],))
        conn.commit()
