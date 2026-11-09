"""PASS-59-264: failure replies that went out at HTTP 200 answer 4xx/5xx.

Each must answer with the status below AND the standard envelope
({success: false, error: str}). No network call is made.
"""
import os
import sqlite3

import pytest

CTRL_ID = 926401  # a controller row this file inserts, with no image


@pytest.fixture
def controller_row():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT OR REPLACE INTO controllers (id, name, image) "
                 "VALUES (?, 'P59264 Pad', NULL)", (CTRL_ID,))
    conn.commit()
    conn.close()
    yield
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("DELETE FROM controllers WHERE id = ?", (CTRL_ID,))
    conn.commit()
    conn.close()


def _assert_failure(resp, status):
    data = resp.get_json()
    assert isinstance(data, dict) and isinstance(data.get('error'), str)
    assert (resp.status_code, data['success']) == (status, False)


def test_museum_upload_with_no_file_is_a_400(controller_row, admin_test_client):
    client, csrf = admin_test_client()
    resp = client.post(f'/api/museum/controller-image-upload/{CTRL_ID}',
                       data={}, headers={'X-CSRF-Token': csrf})
    _assert_failure(resp, 400)


def test_museum_remove_bg_with_no_image_is_a_409(controller_row, admin_test_client):
    client, csrf = admin_test_client()
    resp = client.post(f'/api/museum/controller-image-removebg/{CTRL_ID}',
                       headers={'X-CSRF-Token': csrf})
    _assert_failure(resp, 409)


def test_museum_fetch_with_no_image_found_is_a_404(controller_row, admin_test_client,
                                                    monkeypatch):
    import routes.museum as museum
    monkeypatch.setattr(museum, '_fetch_and_process_image', lambda *a, **k: None)
    client, csrf = admin_test_client()
    resp = client.post(f'/api/museum/controller-image/{CTRL_ID}',
                       headers={'X-CSRF-Token': csrf})
    _assert_failure(resp, 404)


@pytest.mark.parametrize('url', [
    '/api/bulk-scrape-job/cancel',
    '/api/bulk-scrape-job/pause',
    '/api/maintenance/image-resize/cancel',
    '/api/museum/cancel-generate',
])
def test_cancelling_a_job_that_is_not_running_is_a_409(admin_test_client, url):
    client, csrf = admin_test_client()
    resp = client.post(url, headers={'X-CSRF-Token': csrf})
    _assert_failure(resp, 409)


def test_cancelling_another_users_ra_sync_is_a_403(admin_test_client, monkeypatch):
    import services.jobs.base as jobs_base
    monkeypatch.setattr(jobs_base, 'may_control', lambda owner, user: False)
    client, csrf = admin_test_client()
    resp = client.post('/api/achievements/sync-cancel', headers={'X-CSRF-Token': csrf})
    _assert_failure(resp, 403)


def test_job_reply_keeps_200_for_success():
    import app as app_module
    from services.api_helpers import job_reply
    with app_module.app.app_context():
        resp, status = job_reply({'success': True, 'queued': True})
    assert status == 200 and resp.get_json()['queued'] is True


# Launch errors (part 2): the OS's own text stays in the log, the reply is a
# translated sentence that still names the program (user, 2026-11-06).

@pytest.fixture
def launch_client(monkeypatch):
    import app as mod
    from tests.test_routes_launch import _make_authed_client
    monkeypatch.setitem(mod.app.config, 'TESTING', True)
    return _make_authed_client(mod, monkeypatch, 'player')


def test_spawn_failure_names_the_program_but_not_the_os_text(launch_client, monkeypatch):
    from unittest.mock import MagicMock
    from services.launcher import LauncherError
    launcher = MagicMock()
    launcher.active.return_value = []
    launcher.launch.side_effect = LauncherError(
        "failed to spawn /opt/emu/duckstation: [Errno 13] Permission denied")
    monkeypatch.setattr('routes.launch.get_launcher', lambda: launcher)
    monkeypatch.setattr('routes.launch.launches_on_player', lambda gid: False)
    monkeypatch.setattr('routes.launch.resolve_launch_context',
                        lambda gid: MagicMock(is_player=False, argv=['/opt/emu/duckstation']))
    monkeypatch.setattr('routes.launch.apply_for_launch', lambda gid: None)
    monkeypatch.setattr('routes.launch.ra_standalone.apply_for_launch', lambda gid: None)
    resp = launch_client.post('/api/game/1/launch', headers={'X-CSRF-Token': 'test-csrf-token'})
    _assert_failure(resp, 500)
    message = resp.get_json()['error']
    assert '/opt/emu/duckstation' in message
    assert 'Errno' not in message and 'Permission denied' not in message


@pytest.mark.parametrize('method, url', [('get', '/api/launch/gone/status'),
                                         ('post', '/api/launch/gone/kill')])
def test_unknown_launch_token_is_a_translated_404(launch_client, monkeypatch, method, url):
    from unittest.mock import MagicMock
    from services.launcher import LauncherError
    launcher = MagicMock()
    launcher.status.side_effect = launcher.kill.side_effect = LauncherError('unknown token: gone')
    monkeypatch.setattr('routes.launch.get_launcher', lambda: launcher)
    resp = getattr(launch_client, method)(url, headers={'X-CSRF-Token': 'test-csrf-token'})
    _assert_failure(resp, 404)
    assert resp.get_json()['error'] == 'That game is no longer running'
