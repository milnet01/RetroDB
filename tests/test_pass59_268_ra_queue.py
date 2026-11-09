"""PASS-59-268: a RetroAchievements job asked for while another runs waits
on the server, not in one browser tab.

Before, a busy Sync or Refresh replied `queued: true` and the server kept
nothing: the job ran only if that tab stayed open and re-sent it. Now the
server queues it, starts it when RA is idle, and keeps a `job_queue` row so a
restart offers it back. No test reaches RetroAchievements.
"""
import os
import sqlite3
import time

import pytest

SYSTEM_ID = 26801


def _idle():
    return {'running': False, 'completed': False}


def _busy():
    return {'running': True, 'completed': False, 'system_id': None}


def _queued_rows():
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    rows = conn.execute("SELECT job_type, params FROM job_queue "
                        "WHERE status = 'queued' AND job_type LIKE 'ra_%'").fetchall()
    conn.close()
    return rows


@pytest.fixture
def jobs(monkeypatch):
    """The real singletons, with status and start() stubbed: `state` says
    which job is running, `started` records every start()."""
    import app  # noqa: F401 — builds the throwaway schema
    from services import jobs as jobs_pkg
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT OR IGNORE INTO systems (id, name, folder) VALUES (?, 'SNES 268', 'snes')",
                 (SYSTEM_ID,))
    conn.execute("DELETE FROM job_queue WHERE job_type LIKE 'ra_%'")
    conn.commit()
    conn.close()

    state = {'sync': _idle(), 'refresh': _idle()}
    started = []

    def fake_start(kind):
        def start(*args, **kwargs):
            started.append((kind, args, kwargs))
            return {'success': True, 'job_id': f'{kind}-test'}
        return start

    monkeypatch.setattr(jobs_pkg.ra_sync_job, 'get_status', lambda: dict(state['sync']))
    monkeypatch.setattr(jobs_pkg.ra_refresh_job, 'get_status', lambda: dict(state['refresh']))
    monkeypatch.setattr(jobs_pkg.ra_sync_job, 'start', fake_start('sync'))
    monkeypatch.setattr(jobs_pkg.ra_refresh_job, 'start', fake_start('refresh'))
    queue = getattr(jobs_pkg, 'ra_queue', None)
    if queue is not None:
        queue._items.clear()
    yield state, started
    if queue is not None:
        queue._items.clear()
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("DELETE FROM systems WHERE id = ?", (SYSTEM_ID,))
    conn.execute("DELETE FROM job_queue WHERE job_type LIKE 'ra_%'")
    conn.commit()
    conn.close()


def _wait_for(predicate, seconds=6):
    deadline = time.time() + seconds
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.1)
    return predicate()


def test_a_busy_refresh_starts_later_with_no_page_open(jobs, admin_test_client):
    state, started = jobs
    client, csrf = admin_test_client()
    state['sync'] = _busy()

    reply = client.post(f'/api/refresh-retroachievements/{SYSTEM_ID}',
                        headers={'X-CSRF-Token': csrf}).get_json()
    assert reply['success'] is True and reply['queued'] is True
    assert started == []
    assert [r[0] for r in _queued_rows()] == ['ra_refresh']  # survives a restart

    state['sync'] = _idle()  # the running sync ends; no page asks again
    assert _wait_for(lambda: started), 'the queued refresh never started'
    kind, _args, kwargs = started[0]
    assert kind == 'refresh' and kwargs['system_id'] == SYSTEM_ID
    assert _queued_rows() == []


def test_waiting_jobs_are_listed_in_order_and_once(jobs, admin_test_client):
    state, _started = jobs
    client, csrf = admin_test_client()
    state['refresh'] = _busy()
    headers = {'X-CSRF-Token': csrf}

    first = client.post(f'/api/refresh-retroachievements/{SYSTEM_ID}', headers=headers).get_json()
    second = client.post('/api/refresh-retroachievements', headers=headers).get_json()
    again = client.post(f'/api/refresh-retroachievements/{SYSTEM_ID}', headers=headers).get_json()
    assert (first['position'], second['position'], again['position']) == (1, 2, 1)

    listed = client.get('/api/ra-queue').get_json()['queue']
    assert [(i['kind'], i['system_id']) for i in listed] == [('refresh', SYSTEM_ID), ('refresh', None)]
    status = client.get('/api/refresh-retroachievements/status').get_json()
    assert [i['id'] for i in status['ra_queue']] == [i['id'] for i in listed]


def test_cancel_takes_a_waiting_job_out(jobs, admin_test_client):
    state, started = jobs
    client, csrf = admin_test_client()
    state['sync'] = _busy()
    headers = {'X-CSRF-Token': csrf}
    queued = client.post(f'/api/refresh-retroachievements/{SYSTEM_ID}', headers=headers).get_json()

    reply = client.post(f'/api/ra-queue/{queued["queue_id"]}/cancel', headers=headers)
    assert reply.status_code == 200 and reply.get_json()['queue'] == []
    assert _queued_rows() == []
    gone = client.post(f'/api/ra-queue/{queued["queue_id"]}/cancel', headers=headers)
    assert gone.status_code == 404

    state['sync'] = _idle()
    time.sleep(2.5)  # one watcher tick
    assert started == []


def test_another_users_queued_sync_is_not_theirs_to_cancel(jobs, admin_test_client):
    from services.jobs import ra_queue
    jobs[0]['sync'] = _busy()
    item = ra_queue.add('sync', SYSTEM_ID, 'SNES 268', user_id=1)
    client, csrf = admin_test_client(user={'id': 2, 'username': 'ed', 'role': 'editor'})
    reply = client.post(f'/api/ra-queue/{item["id"]}/cancel', headers={'X-CSRF-Token': csrf})
    assert reply.status_code == 403
    assert [i['id'] for i in ra_queue.items()] == [item['id']]


def test_a_sync_waits_for_a_refresh_and_runs_as_its_owner(jobs):
    from services.jobs import ra_queue
    state, started = jobs
    state['refresh'] = _busy()
    ra_queue.add('sync', SYSTEM_ID, 'SNES 268', user_id=7)
    assert ra_queue.start_next() is None and started == []

    state['refresh'] = _idle()
    assert ra_queue.start_next()['kind'] == 'sync'
    kind, args, kwargs = started[0]
    assert (kind, args[0], kwargs['user_id']) == ('sync', SYSTEM_ID, 7)
    assert ra_queue.items() == []


def test_lost_race_for_the_account_waits_again(jobs, monkeypatch):
    from services import jobs as jobs_pkg
    from services.jobs import ra_queue
    monkeypatch.setattr(jobs_pkg.ra_refresh_job, 'start', lambda **kw: {
        'success': False, 'error': 'RA refresh is already running on another worker process.'})
    ra_queue.add('refresh', None, 'All Systems')
    assert ra_queue.start_next() is None
    assert [i['kind'] for i in ra_queue.items()] == ['refresh']
