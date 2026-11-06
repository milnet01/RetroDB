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
