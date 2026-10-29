"""ROM Tools > Bulk AI Fill: the game page's AI Fill run on every game of one
system, or of all systems, for the fields switched on
(services/jobs/ai_fill_bulk.py).

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


@pytest.fixture(autouse=True)
def _fresh_rate_limit():
    """The run route allows 5 starts a minute; these tests start more."""
    import app as app_module
    app_module.limiter.reset()


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


def _run(monkeypatch, system_id, answer, groups=None, include_done=False):
    """Run the job with the AI stubbed: `answer(title)` is what it returns."""
    from scraper import scrape_ai
    from services.jobs.ai_fill_bulk import AiFillBulkJob
    monkeypatch.setattr(scrape_ai, 'get_game_details',
                        lambda game_id, title, *a, **k: answer(title))
    job = AiFillBulkJob()
    assert job.start(system_id, groups, include_done)['success']
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
    assert '<title>Bulk AI Fill - RetroDB</title>' in page
    assert 'id="fillProgressBar" role="progressbar"' in page
    assert '<input type="checkbox" value="units_sold" checked>' in page
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


def test_every_ai_field_has_a_switch():
    from scraper.scrape_ai import AI_FILLABLE_FIELDS
    from services.ai_fill import FIELD_GROUPS
    columns = [c for cols in FIELD_GROUPS.values() for c in cols]
    assert sorted(columns) == sorted(AI_FILLABLE_FIELDS + ['title'])


def test_picks_only_games_with_a_chosen_field_empty(db):
    no_sales = _game(db, 'No Sales', genre='Action')
    sold = _game(db, 'Sold', units_sold=5000)
    zero = _game(db, 'Zero', units_sold=0)
    done = _game(db, 'Done', scrape_history=DONE)
    from services.jobs.ai_fill_bulk import games_to_fill
    pick = lambda **k: {g['id'] for g in games_to_fill(db.conn, db.sids[0], **k)}
    assert pick(groups=['units_sold']) == {no_sales, zero}
    assert pick(groups=['units_sold'], include_done=True) == {no_sales, zero, done}
    assert pick(groups=['genre']) == {sold, zero}
    # A name is never empty: with the official name on, every game counts.
    assert pick(groups=['title']) == {no_sales, sold, zero}


def test_run_writes_only_the_chosen_fields(db, monkeypatch):
    gid = _game(db, 'Grand Theft Auto IV')
    asked = {}
    from scraper import scrape_ai

    def answer(game_id, title, *a, only_fields=None, **k):
        asked['fields'] = only_fields
        return {'units_sold': '11010000', 'genre': 'Action', 'developer': 'Rockstar North'}
    monkeypatch.setattr(scrape_ai, 'get_game_details', answer)
    from services.jobs.ai_fill_bulk import AiFillBulkJob
    job = AiFillBulkJob()
    assert job.start(db.sids[0], ['units_sold', 'genre'])['success']
    job._thread.join(10)
    assert job.get_status()['success'] == 1
    assert asked['fields'] == {'units_sold', 'genre'}
    row = _row(db, gid)
    assert (row['units_sold'], row['genre'], row['developer']) == (11010000, 'Action', None)
    assert row['edition'] is None  # the "Standard Edition" default is a field too


def test_the_ai_is_asked_only_about_the_chosen_fields(monkeypatch):
    from scraper import scrape_ai
    seen = {}

    def fake_call(prompt, api_key, model, **kw):
        seen['prompt'], seen['kw'] = prompt, kw
        return '{"genre": "Action"}'
    monkeypatch.setattr(scrape_ai, '_get_active_provider', lambda: {
        'provider': 'claude', 'api_key': 'k', 'model': 'm', 'web_search': True})
    monkeypatch.setattr(scrape_ai, 'rate_limit', lambda **k: None)
    monkeypatch.setattr(scrape_ai, '_call_claude', fake_call)
    scrape_ai.get_game_details(None, 'Halo 3', 'Microsoft Xbox 360',
                               existing_metadata={}, only_fields={'genre'})
    assert '"genre"' in seen['prompt'] and '"units_sold"' not in seen['prompt']
    # No sales figure asked for, so no paid web searches.
    assert 'web_search' not in seen['kw']


@pytest.mark.parametrize('fields,status', [(['nope'], 400), ([], 400), ('genre', 400)])
def test_run_route_checks_the_fields(fields, status, admin_test_client, monkeypatch):
    from scraper import scrape_ai
    monkeypatch.setattr(scrape_ai, 'active_provider_name', lambda: 'claude')
    client, csrf = admin_test_client()
    resp = client.post('/api/ai-fill-bulk/run', json={'fields': fields},
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == status


def test_count_route_takes_the_switches(db, admin_test_client):
    _game(db, 'Sold', units_sold=5000)
    _game(db, 'Not Sold')
    client, _csrf = admin_test_client()
    url = f'/api/ai-fill-bulk/count?system_id={db.sids[0]}'
    assert client.get(url + '&fields=units_sold').get_json()['count'] == 1
    assert client.get(url + '&fields=bogus').status_code == 400


def test_status_reply_is_flat_for_the_toast(admin_test_client):
    client, _csrf = admin_test_client()
    body = client.get('/api/ai-fill-bulk/status').get_json()
    assert {'running', 'completed', 'percent', 'current_game', 'system_name'} <= set(body)


def test_toast_knows_the_ai_fill_run():
    src = open('static/js/toast-controller.js').read()
    assert "this.pollingEndpoints.set('ai-fill', '/api/ai-fill-bulk/status');" in src
    assert "endpoint = '/api/ai-fill-bulk/cancel';" in src
    # Toast colours are theme variables, not fixed colours.
    types = src.split('const ToastTypes = {', 1)[1].split('};', 1)[0]
    assert '#' not in types


def test_a_toast_without_a_paused_field_is_not_shown_paused():
    """classList.toggle('paused', undefined) flips the class, so a job whose
    status has no `paused` field drew its toast title as paused."""
    src = open('static/js/toast-controller.js').read()
    assert 'const isPaused = data.paused;' not in src
