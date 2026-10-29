"""Bulk AI Fill on ROM Tools > Official Names: the game page's AI Fill run on
every game of one system, or of all systems (services/jobs/ai_fill_bulk.py).

Route and job tests use the throwaway schema conftest points
RETRODB_DB_PATH at.
"""
import json
import os
import sqlite3
from types import SimpleNamespace

import pytest

FOLDER = 'aifillbulk'
VIEWER = {'id': 1, 'username': 'viewer-stub', 'role': 'viewer'}


@pytest.fixture
def db():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                 "VALUES (1, 'admin-stub', 'x', 'admin')")
    sids = []
    for n in range(2):
        conn.execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                     (f'AI Fill Bulk {n}', f'{FOLDER}{n}'))
        sids.append(conn.execute("SELECT id FROM systems WHERE folder = ?",
                                 (f'{FOLDER}{n}',)).fetchone()[0])
    conn.commit()
    yield SimpleNamespace(conn=conn, sids=sids)
    for sid in sids:
        conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
        conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
    conn.commit()
    conn.close()


def _game(d, title, system=0, **cols):
    cols = {'rom_path': f'/roms/{FOLDER}/{title}.zip', **cols}
    names = ''.join(f', {c}' for c in cols)
    cur = d.conn.execute(
        f"INSERT INTO games (system_id, title{names}) VALUES (?, ?{', ?' * len(cols)})",
        (d.sids[system], title, *cols.values()))
    d.conn.commit()
    return cur.lastrowid


def _row(d, game_id):
    return d.conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()


DONE = json.dumps([{'primary_source': 'AI Fill', 'scrape_mode': 'ai_fill'}])
SCRAPED = json.dumps([{'primary_source': 'IGDB', 'scrape_mode': 'fill_missing'}])


def _ids(d, system_id):
    from services.jobs.ai_fill_bulk import games_to_fill
    return {g['id'] for g in games_to_fill(d.conn, system_id)}


def test_picks_games_ai_fill_has_not_done(db):
    new = _game(db, 'New')
    scraped = _game(db, 'Scraped', scrape_history=SCRAPED)
    done = _game(db, 'Done', scrape_history=DONE)
    other = _game(db, 'Other System', system=1)
    assert _ids(db, db.sids[0]) == {new, scraped}
    every = _ids(db, None)
    assert {new, scraped, other} <= every and done not in every


def _run(monkeypatch, system_id, answer):
    """Run the job with the AI stubbed: `answer(title)` is what it returns."""
    from scraper import scrape_ai
    from services.jobs.ai_fill_bulk import AiFillBulkJob
    monkeypatch.setattr(scrape_ai, 'get_game_details',
                        lambda game_id, title, *a, **k: answer(title))
    job = AiFillBulkJob()
    assert job.start(system_id)['success']
    job._thread.join(10)
    status = job.get_status()
    assert status['completed'], status
    return status


def test_run_fills_and_a_second_run_skips(db, monkeypatch):
    gid = _game(db, 'Grand Theft Auto IV')
    status = _run(monkeypatch, db.sids[0], lambda t: {'units_sold': '11010000'})
    assert (status['success'], status['total'], status['error']) == (1, 1, None)
    row = _row(db, gid)
    assert row['units_sold'] == 11010000
    assert json.loads(row['scrape_history'])[-1]['scrape_mode'] == 'ai_fill'
    assert _run(monkeypatch, db.sids[0], lambda t: {'units_sold': '1'})['total'] == 0
    assert _row(db, gid)['units_sold'] == 11010000


def test_run_stops_when_the_ai_keeps_failing(db, monkeypatch):
    """A refused key or no credit fails every game; stop instead of trying
    the whole library."""
    from services.jobs.ai_fill_bulk import MAX_FAILURES_IN_A_ROW
    for n in range(MAX_FAILURES_IN_A_ROW + 2):
        _game(db, f'Game {n}')
    status = _run(monkeypatch, db.sids[0], lambda t: None)
    assert status['failed'] == MAX_FAILURES_IN_A_ROW
    assert status['error'] and 'no answer' in status['error']


def test_one_failure_does_not_stop_the_run(db, monkeypatch):
    for title in ('A', 'B', 'C'):
        _game(db, title)
    status = _run(monkeypatch, db.sids[0],
                  lambda t: None if t == 'B' else {'units_sold': '5000'})
    assert (status['success'], status['failed'], status['error']) == (2, 1, None)


def test_count_route(db, admin_test_client):
    _game(db, 'One')
    _game(db, 'Two')
    _game(db, 'Done', scrape_history=DONE)
    client, _csrf = admin_test_client()
    body = client.get(f'/api/ai-fill-bulk/count?system_id={db.sids[0]}').get_json()
    assert body['count'] == 2


@pytest.mark.parametrize('system_id', ['3', True, 1.5])
def test_run_route_refuses_a_bad_system(system_id, admin_test_client, monkeypatch):
    from scraper import scrape_ai
    monkeypatch.setattr(scrape_ai, 'active_provider_name', lambda: 'claude')
    client, csrf = admin_test_client()
    resp = client.post('/api/ai-fill-bulk/run', json={'system_id': system_id},
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 400


def test_run_route_needs_an_ai_provider(admin_test_client, monkeypatch):
    from scraper import scrape_ai
    monkeypatch.setattr(scrape_ai, 'active_provider_name', lambda: '')
    client, csrf = admin_test_client()
    resp = client.post('/api/ai-fill-bulk/run', json={}, headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 400
    assert 'Settings > Scraping' in resp.get_json()['error']


@pytest.mark.parametrize('method,url', [
    ('get', '/api/ai-fill-bulk/count'),
    ('post', '/api/ai-fill-bulk/run'),
    ('get', '/api/ai-fill-bulk/status'),
    ('post', '/api/ai-fill-bulk/cancel'),
])
def test_routes_need_editor(method, url, admin_test_client):
    client, csrf = admin_test_client(user=VIEWER)
    resp = getattr(client, method)(url, json={}, headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 403, (url, resp.status_code)


def test_page_has_the_fill_card(admin_test_client, db):
    client, _csrf = admin_test_client()
    page = client.get('/tools/official-names').get_data(as_text=True)
    assert 'id="aiFillBulk"' in page and 'id="fillSystem"' in page
    block = page.split('id="fillSystem"', 1)[1].split('</select>', 1)[0]
    assert '<option value="">All systems</option>' in block
    assert f'<option value="{db.sids[0]}">' not in block  # no games yet, not listed


def test_job_is_drained_and_resumable():
    from services.jobs import ai_fill_bulk_job
    from services.jobs.ai_fill_bulk import AiFillBulkJob
    import app as app_module
    assert isinstance(ai_fill_bulk_job, AiFillBulkJob)
    assert 'ai_fill_bulk' in app_module._RESUMABLE_JOB_TYPES
    src = open('services/jobs/base.py').read()
    assert "getattr(_jobs_pkg, 'ai_fill_bulk_job', None)" in src
