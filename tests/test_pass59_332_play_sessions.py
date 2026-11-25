"""PASS-59-332: play sessions, and a completion status for each person.

One test per invariant in docs/specs/PASS-59-332-play-sessions.md §5. The
DB tests work on the throwaway schema conftest points RETRODB_DB_PATH at,
inside users, a system and games this module creates and removes.
"""
import os
import sqlite3
import sys
import threading
import time
from types import SimpleNamespace

import pytest

FOLDER = 'pass59332'
ALICE = {'id': 33201, 'username': 'p332-alice', 'role': 'admin'}
BOB = {'id': 33202, 'username': 'p332-bob', 'role': 'viewer'}


@pytest.fixture
def db():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.row_factory = sqlite3.Row
    for u in (ALICE, BOB):
        conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                     "VALUES (?, ?, 'x', ?)", (u['id'], u['username'], u['role']))
    conn.execute("INSERT INTO systems (name, folder) VALUES ('Pass 59-332', ?)", (FOLDER,))
    sid = conn.execute("SELECT id FROM systems WHERE folder = ?", (FOLDER,)).fetchone()[0]
    conn.commit()
    yield SimpleNamespace(conn=conn, sid=sid)
    conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
    conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
    conn.execute("DELETE FROM users WHERE id IN (?, ?)", (ALICE['id'], BOB['id']))
    conn.commit()
    conn.close()


def _game(d, title, **cols):
    cols = {'rom_path': f'/roms/{FOLDER}/{title}.zip', **cols}
    names = ', '.join(cols)
    cur = d.conn.execute(
        f"INSERT INTO games (system_id, title, {names}) VALUES (?, ?, {', '.join('?' * len(cols))})",
        (d.sid, title, *cols.values()))
    d.conn.commit()
    return cur.lastrowid


def _detail_status(client, gid):
    resp = client.get(f'/api/game/{gid}/detail')
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return resp.get_json()['game']['completion_status']


# INV-1 — one person's status never changes another's.
def test_status_is_per_person(db, admin_test_client):
    gid = _game(db, 'Shared Game', completion_status='not_started')
    alice, csrf = admin_test_client(user=ALICE)
    resp = alice.post(f'/api/game/{gid}/completion', json={'status': 'completed'},
                      headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    resp = alice.post('/api/games/bulk-edit',
                      json={'game_ids': [gid], 'fields': {'completion_status': 'played'}},
                      headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert _detail_status(alice, gid) == 'played'

    bob, csrf = admin_test_client(user=BOB)
    assert _detail_status(bob, gid) == 'not_started'
    # A viewer sets their own status (track_progress), and only their own.
    resp = bob.post(f'/api/game/{gid}/completion', json={'status': 'in_progress'},
                    headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert _detail_status(bob, gid) == 'in_progress'

    alice, _csrf = admin_test_client(user=ALICE)
    assert _detail_status(alice, gid) == 'played'
    resp = alice.get(f'/api/games/card-data?ids={gid}')
    assert resp.get_json()['games'][0]['completion_status'] == 'played'
    # Nothing writes the old shared column.
    assert db.conn.execute("SELECT completion_status FROM games WHERE id = ?",
                           (gid,)).fetchone()[0] == 'not_started'


# INV-2 — the migration gives the first admin every set status, others none.
def _load_048():
    import importlib
    return importlib.import_module('services.migrations.scripts.048_play_sessions')


def test_migration_copies_to_admin_only():
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, completion_status TEXT)")
    conn.executemany("INSERT INTO users VALUES (?, ?, ?)",
                     [(1, 'viewer', 'viewer'), (2, 'first', 'admin'), (3, 'second', 'admin')])
    conn.executemany("INSERT INTO games VALUES (?, ?)",
                     [(10, 'completed'), (11, 'not_started'), (12, None),
                      (13, 'in_progress'), (14, '')])
    migration = _load_048()
    migration.apply(conn)
    migration.apply(conn)                      # runs twice without harm
    rows = conn.execute("SELECT user_id, game_id, status, set_by FROM user_game_status "
                        "ORDER BY game_id").fetchall()
    assert rows == [(2, 10, 'completed', 'hand'), (2, 13, 'in_progress', 'hand')]

    # No admin: nothing is copied.
    empty = sqlite3.connect(':memory:')
    empty.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, role TEXT)")
    empty.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, completion_status TEXT)")
    empty.execute("INSERT INTO games VALUES (10, 'completed')")
    migration.apply(empty)
    assert empty.execute("SELECT COUNT(*) FROM user_game_status").fetchone()[0] == 0


def _status_row(d, user_id, gid):
    return d.conn.execute("SELECT * FROM user_game_status WHERE user_id = ? AND game_id = ?",
                          (user_id, gid)).fetchone()


def _session(user_id, gid, seconds, save_changed=False, achievement=False):
    from services import game_status
    return game_status.record_session(user_id, gid, None, int(time.time()) - seconds,
                                      seconds, save_changed, achievement)


# INV-3 — play moves only an untouched Not Started, and only to In Progress.
def test_play_moves_only_untouched_not_started(db):
    from services import game_status
    uid = ALICE['id']
    for status in ('in_progress', 'played', 'completed', '100_percent', 'not_started'):
        gid = _game(db, f'Hand {status}')
        game_status.set_by_hand(uid, [gid], status)
        assert _session(uid, gid, 1200, save_changed=True) is None
        assert game_status.status_for(uid, gid) == status

    gid = _game(db, 'Untouched')
    assert _session(uid, gid, 1200, save_changed=True) == 'moved'
    row = _status_row(db, uid, gid)
    assert (row['status'], row['set_by']) == ('in_progress', 'play')

    gid = _game(db, 'By achievement')
    assert _session(uid, gid, 1200, achievement=True) == 'moved'
    assert game_status.status_for(uid, gid) == 'in_progress'
    assert game_status.status_for(BOB['id'], gid) == 'not_started'


# INV-4 — under 10 minutes nothing moves and nothing is asked.
def test_short_session_changes_nothing(db):
    from services import game_status
    gid = _game(db, 'Short')
    assert _session(ALICE['id'], gid, 599, save_changed=True, achievement=True) is None
    assert _status_row(db, ALICE['id'], gid) is None
    assert game_status.play_seconds(ALICE['id'], gid) == 599


# INV-5 — the question is asked once per person per game.
def test_question_is_asked_once(db):
    from services import game_status
    uid = ALICE['id']
    gid = _game(db, 'Long and quiet')
    assert _session(uid, gid, 1800) == 'ask'
    assert game_status.pending_question(uid, gid)
    assert _session(uid, gid, 1800) is None          # still waiting: not asked twice
    assert game_status.answer(uid, gid, False)
    assert not game_status.pending_question(uid, gid)
    assert _session(uid, gid, 1800) is None
    assert game_status.status_for(uid, gid) == 'not_started'
    row = _status_row(db, uid, gid)
    assert (row['asked'], row['ask_pending']) == (1, 0)
    # Another person is asked for themselves.
    assert _session(BOB['id'], gid, 1800) == 'ask'

    gid2 = _game(db, 'Answered yes')
    _session(uid, gid2, 1800)
    assert game_status.answer(uid, gid2, True)
    row = _status_row(db, uid, gid2)
    assert (row['status'], row['set_by']) == ('in_progress', 'hand')


def _launch(user_id, gid, argv, on_exit=None):
    from services.launcher.base import LaunchContext
    from services.launcher.local import LocalLauncher
    launcher = LocalLauncher()
    ctx = LaunchContext(game_id=gid, emulator_id=0, binary=argv[0], argv=argv,
                        token=f'p332-{gid}', on_exit=on_exit)
    ctx.user_id = user_id
    launcher.launch(ctx)
    return launcher, ctx.token


# INV-6 — a session is recorded when the process exits, with nothing polling.
def test_session_recorded_without_polling(db):
    gid = _game(db, 'Unpolled')
    launcher, token = _launch(ALICE['id'], gid, [sys.executable, '-c', 'pass'])
    entry = launcher._registry.get(token)
    entry.drain.join(timeout=10)
    assert not entry.drain.is_alive()
    assert entry.exit_time is None                 # nothing polled it
    rows = db.conn.execute("SELECT user_id, seconds FROM play_sessions WHERE game_id = ?",
                           (gid,)).fetchall()
    assert [r['user_id'] for r in rows] == [ALICE['id']]
    assert rows[0]['seconds'] < 60


# INV-7 — the analytics numbers are the asking person's.
def test_analytics_is_per_person(db):
    from services import analytics, game_status
    gid = _game(db, 'Finished by Alice')
    game_status.set_by_hand(ALICE['id'], [gid], 'completed')
    analytics.invalidate_analytics_cache()
    alice_done = analytics.build_analytics_context(ALICE['id'])['completion_data'][3]
    bob_done = analytics.build_analytics_context(BOB['id'])['completion_data'][3]
    assert alice_done >= 1
    assert bob_done == alice_done - 1


# INV-8 — a recording failure never stops the launcher or on_exit.
def test_recording_failure_is_contained(db, monkeypatch):
    from services import game_status
    errors = []
    monkeypatch.setattr(threading, 'excepthook', lambda a: errors.append(a.exc_value))

    def _boom(*_a, **_k):
        raise sqlite3.OperationalError('database is locked')

    monkeypatch.setattr(game_status, 'record_session', _boom)
    ran = []
    gid = _game(db, 'Failing record')
    launcher, token = _launch(ALICE['id'], gid, [sys.executable, '-c', 'pass'],
                              on_exit=lambda: ran.append(1))
    entry = launcher._registry.get(token)
    entry.drain.join(timeout=10)
    assert errors == []
    assert launcher.status(token).state == 'exited'
    assert ran == [1]
