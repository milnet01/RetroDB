"""PASS-59-116: the Museum's "Fetch All Images" runs as a background job.

The start reply comes back at once with a job id; the job fills each
controller with no image, skips the ones that have one, and stops when
cancelled. No network call is made: the image fetch is stubbed.
"""
import os
import sqlite3
import threading

import pytest


@pytest.fixture
def museum_db():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.row_factory = sqlite3.Row
    sys_id = conn.execute("INSERT INTO systems (name, folder) VALUES ('Museum 59116', 'm59116')"
                          ).lastrowid
    ctrl_ids = []
    for name, image in (('Pad A 59116', None), ('Pad B 59116', 'have.webp'),
                        ('Pad C 59116', None)):
        cid = conn.execute("INSERT INTO controllers (name, image) VALUES (?, ?)",
                           (name, image)).lastrowid
        conn.execute("INSERT INTO system_controllers (system_id, controller_id) VALUES (?, ?)",
                     (sys_id, cid))
        ctrl_ids.append(cid)
    conn.commit()
    yield conn, sys_id, ctrl_ids
    conn.execute("DELETE FROM system_controllers WHERE system_id = ?", (sys_id,))
    conn.execute("DELETE FROM controllers WHERE id IN (?, ?, ?)", ctrl_ids)
    conn.execute("DELETE FROM systems WHERE id = ?", (sys_id,))
    conn.commit()
    conn.close()


@pytest.fixture
def no_pause(monkeypatch):
    import routes.museum as museum
    monkeypatch.setattr(museum, '_get_removebg_key', lambda: '')
    try:
        import services.jobs.museum_images as job_mod
        monkeypatch.setattr(job_mod, 'shutdown_requested',
                            type('E', (), {'wait': staticmethod(lambda s: None)})())
    except ImportError:
        pass
    return museum


def _wait_done():
    from services.jobs import museum_images_job
    if museum_images_job._thread:
        museum_images_job._thread.join(timeout=10)
    return museum_images_job.get_status()


def test_start_replies_at_once_and_the_job_fills_missing_images(
        museum_db, no_pause, monkeypatch, admin_test_client):
    conn, sys_id, (a, b, c) = museum_db
    calls = []
    monkeypatch.setattr(no_pause, '_fetch_and_process_image',
                        lambda cid, *rest: calls.append(cid) or f'ctrl_{cid}.webp')
    client, csrf = admin_test_client()
    body = client.post(f'/api/museum/controller-images-bulk/{sys_id}',
                       headers={'X-CSRF-Token': csrf}).get_json()
    assert body['success'] is True and isinstance(body.get('job_id'), str)
    status = _wait_done()
    assert (status['success'], status['skipped'], status['failed']) == (2, 1, 0)
    assert sorted(calls) == sorted([a, c])
    images = dict(conn.execute("SELECT id, image FROM controllers WHERE id IN (?, ?, ?)",
                               (a, b, c)).fetchall())
    assert images == {a: f'ctrl_{a}.webp', b: 'have.webp', c: f'ctrl_{c}.webp'}


def test_cancel_stops_the_fetch(museum_db, no_pause, monkeypatch, admin_test_client):
    conn, sys_id, (a, _b, c) = museum_db
    entered, release = threading.Event(), threading.Event()
    calls = []

    def slow_fetch(cid, *rest):
        calls.append(cid)
        entered.set()
        release.wait(5)
        return None

    monkeypatch.setattr(no_pause, '_fetch_and_process_image', slow_fetch)
    client, csrf = admin_test_client()
    client.post(f'/api/museum/controller-images-bulk/{sys_id}', headers={'X-CSRF-Token': csrf})
    assert entered.wait(5)
    cancel = client.post('/api/museum/controller-images-bulk/cancel',
                         headers={'X-CSRF-Token': csrf}).get_json()
    release.set()
    status = _wait_done()
    assert cancel['success'] is True
    assert status['cancelled'] is True and calls == [a]


def test_no_controllers_is_a_404(no_pause, admin_test_client):
    client, csrf = admin_test_client()
    resp = client.post('/api/museum/controller-images-bulk/987654321',
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 404 and resp.get_json()['success'] is False
