"""PASS-59-159 — official names and the title lock
(docs/specs/PASS-59-159-official-names.md §5, one test per invariant).

Scraper tests run against a fresh database built by the real migrations;
route tests use the throwaway schema conftest points RETRODB_DB_PATH at.
"""
import os
import sqlite3
from types import SimpleNamespace

import pytest

from services import migrations

SCRAPED_NAME = 'Mega Man'
LOCKED_NAME = 'Rockman'


# ---------------------------------------------------------------------------
# INV-1 / INV-2 — the four scraper title writes honour the lock
# ---------------------------------------------------------------------------

@pytest.fixture
def scrape_db(tmp_path, monkeypatch):
    """A migrated database with one game, and a connect() each scraper is
    pointed at. HOME moves to tmp so ES-DE finds no real media folder."""
    path = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(path)
    migrations.apply_pending(conn)
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'NES', 'nes')")
    conn.execute("INSERT INTO games (id, system_id, title, sort_title, rom_path) "
                 "VALUES (1, 1, ?, ?, '/roms/nes/Rockman (Japan).nes')",
                 (LOCKED_NAME, LOCKED_NAME))
    conn.commit()
    conn.close()

    def connect():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setenv('HOME', str(tmp_path))
    return connect


def _set_lock(connect, locked):
    c = connect()
    c.execute("UPDATE games SET title_locked = ? WHERE id = 1", (int(locked),))
    c.commit()
    c.close()


def _titles(connect):
    c = connect()
    try:
        row = c.execute("SELECT title, sort_title FROM games WHERE id = 1").fetchone()
        return row['title'], row['sort_title']
    finally:
        c.close()


def _scrape_igdb(connect, monkeypatch):
    from scraper import scrape_igdb
    monkeypatch.setattr(scrape_igdb, 'get_scraper_conn', connect)
    monkeypatch.setattr(scrape_igdb, 'download_image', lambda *a, **k: None)
    assert scrape_igdb.apply_metadata_to_game(1, {'name': SCRAPED_NAME}) is True


def _scrape_tgdb(connect, monkeypatch):
    from scraper import scrape_thegamesdb
    monkeypatch.setattr(scrape_thegamesdb, 'get_scraper_conn', connect)
    monkeypatch.setattr(scrape_thegamesdb, '_download_tgdb_image',
                        lambda *a, **k: None, raising=False)
    assert scrape_thegamesdb.apply_metadata_to_game(1, {'game_title': SCRAPED_NAME}) is True


def _scrape_esde(connect, monkeypatch):
    from scraper import scrape_esde
    monkeypatch.setattr(scrape_esde, 'get_scraper_conn', connect)
    monkeypatch.setattr(scrape_esde, '_get_esde_gamelists_path', lambda: None)
    monkeypatch.setattr(scrape_esde, '_get_esde_media_path', lambda: None)
    assert scrape_esde.apply_esde_metadata(1, {'name': SCRAPED_NAME}) is True


def _scrape_hybrid(connect, monkeypatch):
    from scraper import hybrid_scraper
    from tests.test_pass38_save_game_row_helper import _full_metadata
    conn = connect()
    hybrid_scraper._save_game_row(
        conn.cursor(), _full_metadata(title=SCRAPED_NAME, sort_title=SCRAPED_NAME), '[]', 1)
    conn.commit()
    conn.close()


SCRAPERS = {'igdb': _scrape_igdb, 'tgdb': _scrape_tgdb,
            'esde': _scrape_esde, 'hybrid': _scrape_hybrid}


@pytest.mark.parametrize('site', SCRAPERS)
def test_locked_title_survives_scrape(site, scrape_db, monkeypatch):
    """INV-1. Full Re-scrape reaches the same `_save_game_row` SQL with the
    source's values, so the hybrid case covers both modes."""
    _set_lock(scrape_db, True)
    SCRAPERS[site](scrape_db, monkeypatch)
    assert _titles(scrape_db) == (LOCKED_NAME, LOCKED_NAME)


@pytest.mark.parametrize('site', SCRAPERS)
def test_unlocked_title_still_scraped(site, scrape_db, monkeypatch):
    """INV-2."""
    SCRAPERS[site](scrape_db, monkeypatch)
    assert _titles(scrape_db)[0] == SCRAPED_NAME


# ---------------------------------------------------------------------------
# INV-8 — the edit windows lock, Reset unlocks, Clear scraped data spares
# ---------------------------------------------------------------------------

FOLDER = 'pass59159names'


@pytest.fixture
def db():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                 "VALUES (1, 'admin-stub', 'x', 'admin')")
    conn.execute("INSERT INTO systems (name, folder) VALUES ('Pass 59-159', ?)", (FOLDER,))
    sid = conn.execute("SELECT id FROM systems WHERE folder = ?", (FOLDER,)).fetchone()[0]
    conn.commit()
    yield SimpleNamespace(conn=conn, sid=sid)
    conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
    conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
    conn.commit()
    conn.close()


def _game(d, title, rom='Rockman 2 (Japan).nes', **cols):
    cols = {'rom_path': f'/roms/{FOLDER}/{rom}', **cols}
    names = ', '.join(cols)
    cur = d.conn.execute(
        f"INSERT INTO games (system_id, title, {names}) VALUES (?, ?, {', '.join('?' * len(cols))})",
        (d.sid, title, *cols.values()))
    d.conn.commit()
    return cur.lastrowid


def _row(d, game_id):
    return d.conn.execute("SELECT * FROM games WHERE id = ?", (game_id,)).fetchone()


def _json_edit(client, csrf, gid, **body):
    resp = client.post(f'/api/game/{gid}/edit', json=body, headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]


def _form_post(client, csrf, gid, **fields):
    resp = client.post(f'/game/{gid}', data={'_csrf_token': csrf, **fields})
    assert resp.status_code in (200, 302), resp.get_data(as_text=True)[:300]


def test_lock_set_and_cleared(db, admin_test_client):
    """INV-8: the three rows of §4.3's table, through both edit windows."""
    client, csrf = admin_test_client()

    # Library pop-up (JSON): a changed title locks; unticking unlocks.
    gid = _game(db, SCRAPED_NAME)
    _json_edit(client, csrf, gid, title=LOCKED_NAME, title_locked=False)
    assert _row(db, gid)['title_locked'] == 1
    _json_edit(client, csrf, gid, title=LOCKED_NAME, title_locked=False)
    assert _row(db, gid)['title_locked'] == 0
    # A save that names neither leaves the lock as it is.
    _json_edit(client, csrf, gid, title_locked=True)
    _json_edit(client, csrf, gid, publisher='Capcom')
    assert _row(db, gid)['title_locked'] == 1

    # Game page form: a changed title locks.
    gid2 = _game(db, SCRAPED_NAME, rom='Rockman 3 (Japan).nes')
    _form_post(client, csrf, gid2, action='edit_metadata', edit_title=LOCKED_NAME)
    row = _row(db, gid2)
    assert (row['title'], row['title_locked']) == (LOCKED_NAME, 1)

    # Clear scraped data leaves the locked title alone ...
    import app as app_module
    from services.game_cleanup import clear_scraped_data
    db.conn.execute("UPDATE games SET scraped = 1 WHERE system_id = ?", (db.sid,))
    db.conn.commit()
    with app_module.app.app_context():
        clear_scraped_data(system_id=db.sid)
    row = _row(db, gid2)
    assert (row['title'], row['title_locked']) == (LOCKED_NAME, 1)

    # ... and the per-game Reset unlocks it and takes the filename's title.
    _form_post(client, csrf, gid2, action='reset')
    row = _row(db, gid2)
    assert row['title_locked'] == 0
    assert row['title'] != LOCKED_NAME


# ---------------------------------------------------------------------------
# INV-3 / INV-6 — the run stores proposals and never writes `games`
# ---------------------------------------------------------------------------

def _run(monkeypatch, system_id, answer):
    """Run the job over one system with the AI call stubbed: `answer(game)`
    gives the official title the stub proposes for each game."""
    from scraper import scrape_ai
    from services.jobs.official_names import OfficialNamesJob
    monkeypatch.setattr(scrape_ai, 'propose_official_names', lambda system, games: [
        {'official_title': answer(g), 'old_title_region': 'US'} for g in games])
    job = OfficialNamesJob()
    assert job.start(system_id)['success']
    job._thread.join(10)
    status = job.get_status()
    assert status['completed'] and not status['error'], status
    return status


def _proposal(d, gid):
    return d.conn.execute("SELECT * FROM title_proposals WHERE game_id = ?", (gid,)).fetchone()


def test_run_changes_no_title(db, monkeypatch):
    """INV-3."""
    ids = [_game(db, f'Game {n}', rom=f'Game {n} (Japan).nes') for n in range(3)]
    locked = _game(db, 'Locked', rom='Locked (Japan).nes', title_locked=1)
    query = "SELECT * FROM games WHERE system_id = ? ORDER BY id"
    before = [tuple(r) for r in db.conn.execute(query, (db.sid,))]
    status = _run(monkeypatch, db.sid, lambda g: g['title'] + ' Official')
    assert [tuple(r) for r in db.conn.execute(query, (db.sid,))] == before
    assert status['proposals'] == 3
    assert _proposal(db, ids[0])['proposed_title'] == 'Game 0 Official'
    assert _proposal(db, locked) is None


def test_rejected_not_reproposed(db, monkeypatch):
    """INV-6."""
    gid = _game(db, SCRAPED_NAME)
    db.conn.execute("INSERT INTO title_proposals (game_id, old_title, proposed_title, status) "
                    "VALUES (?, ?, ?, 'rejected')", (gid, SCRAPED_NAME, LOCKED_NAME))
    db.conn.commit()
    _run(monkeypatch, db.sid, lambda g: LOCKED_NAME)
    assert _proposal(db, gid)['status'] == 'rejected'
    _run(monkeypatch, db.sid, lambda g: 'Rockman World')
    row = _proposal(db, gid)
    assert (row['status'], row['proposed_title']) == ('pending', 'Rockman World')


# ---------------------------------------------------------------------------
# INV-4 / INV-5 — accept
# ---------------------------------------------------------------------------

def _propose(d, gid, old, new, region='US'):
    d.conn.execute("INSERT INTO title_proposals (game_id, old_title, proposed_title, "
                   "old_title_region) VALUES (?, ?, ?, ?)", (gid, old, new, region))
    d.conn.commit()


def _accept(client, csrf, ids):
    resp = client.post('/api/official-names/accept', json={'game_ids': ids},
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return resp.get_json()


def test_accept_applies(db, admin_test_client):
    """INV-4."""
    import json
    gid = _game(db, SCRAPED_NAME, alternate_titles=json.dumps([{'title': 'ROCKMAN'}]))
    _propose(db, gid, SCRAPED_NAME, 'Rockman 2: Dr. Wily no Nazo')
    client, csrf = admin_test_client()
    assert _accept(client, csrf, [gid])['accepted'] == 1
    row = _row(db, gid)
    assert row['title'] == 'Rockman 2: Dr. Wily no Nazo'
    assert row['sort_title'] and row['sort_title'] != SCRAPED_NAME
    assert row['title_locked'] == 1
    alts = json.loads(row['alternate_titles'])
    assert {'title': SCRAPED_NAME, 'region': 'US', 'source': 'official_names'} in alts
    assert _proposal(db, gid) is None
    assert json.loads(row['scrape_history'])[-1]['primary_source'] == 'official_names'


def test_accept_drops_alt_equal_to_new_title(db, admin_test_client):
    """INV-4, last clause: a stored alt equal to the new title goes."""
    import json
    gid = _game(db, SCRAPED_NAME, alternate_titles=json.dumps([{'title': 'ROCKMAN'}]))
    _propose(db, gid, SCRAPED_NAME, LOCKED_NAME)
    client, csrf = admin_test_client()
    _accept(client, csrf, [gid])
    titles = [a['title'] for a in json.loads(_row(db, gid)['alternate_titles'])]
    assert titles == [SCRAPED_NAME]


def test_accept_skips_stale(db, admin_test_client):
    """INV-5."""
    gid = _game(db, 'Typed Since')
    _propose(db, gid, SCRAPED_NAME, LOCKED_NAME)
    client, csrf = admin_test_client()
    assert _accept(client, csrf, [gid])['skipped'] == 1
    assert _row(db, gid)['title'] == 'Typed Since'
    assert _proposal(db, gid) is None


# ---------------------------------------------------------------------------
# INV-7 — model output is untrusted
# ---------------------------------------------------------------------------

def test_parse_rejects_bad_entries():
    import json
    from scraper.scrape_ai import _parse_official_names
    reply = json.dumps([
        {'i': 3, 'official_title': 'Fourth', 'old_title_region': 'Japan'},
        {'i': 9, 'official_title': 'Out of range'},
        {'i': '1', 'official_title': 'String index'},
        {'i': True, 'official_title': 'Bool index'},
        {'i': 0, 'official_title': 42},
        {'i': 1, 'official_title': 'x' * 201},
        {'i': 2, 'official_title': 'Bad\x07Title'},
        {'official_title': 'No index'},
    ])
    answers = _parse_official_names('```json\n' + reply + '\n```', 4)
    assert [a['official_title'] for a in answers] == [None, None, None, 'Fourth']
    assert answers[3]['old_title_region'] == 'JP'
    assert _parse_official_names('not json', 2) == [
        {'official_title': None, 'old_title_region': None}] * 2


# ---------------------------------------------------------------------------
# INV-9 — every route needs an editor
# ---------------------------------------------------------------------------

VIEWER = {'id': 1, 'username': 'viewer-stub', 'role': 'viewer'}


@pytest.mark.parametrize('method,url', [
    ('get', '/tools/official-names'),
    ('get', '/api/official-names/proposals'),
    ('post', '/api/official-names/accept'),
    ('post', '/api/official-names/reject'),
    ('post', '/api/official-names/run'),
    ('get', '/api/official-names/status'),
    ('post', '/api/official-names/cancel'),
])
def test_routes_need_editor(method, url, admin_test_client):
    client, csrf = admin_test_client(user=VIEWER)
    resp = getattr(client, method)(url, json={}, headers={'X-CSRF-Token': csrf})
    # A page redirects a non-editor away; an API refuses with 403.
    assert resp.status_code in (302, 403), (url, resp.status_code)
