"""PASS-59-58: a PSN reply that omits a trophy-count block keeps the stored
counts, in both the single-game sync and the full-sync upsert."""
import os
import sqlite3
from types import SimpleNamespace

import pytest

NPWR = 'NPWR59058_00'
STORED = dict(progress=50, earned_platinum=1, earned_gold=2, earned_silver=3,
              earned_bronze=4, total_platinum=1, total_gold=4, total_silver=6,
              total_bronze=9, total_trophies=20, earned_trophies=10)


def _counts(p, g, s, b):
    return SimpleNamespace(platinum=p, gold=g, silver=s, bronze=b)


def _title(earned=None, defined=None):
    return SimpleNamespace(np_communication_id=NPWR, title_name='Test Game',
                           earned_trophies=earned, defined_trophies=defined,
                           title_icon_url=None, title_platform=frozenset())


@pytest.fixture
def db():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.row_factory = sqlite3.Row
    conn.execute("INSERT OR IGNORE INTO users (id, username, password_hash, role) "
                 "VALUES (1, 'admin-stub', 'x', 'admin')")
    conn.execute("DELETE FROM psn_games WHERE npwr_id = ?", (NPWR,))
    cols = ', '.join(STORED)
    conn.execute(f"INSERT INTO psn_games (npwr_id, user_id, title, platform, {cols}) "
                 f"VALUES (?, 1, 'Test Game', 'PS4', {', '.join('?' * len(STORED))})",
                 (NPWR, *STORED.values()))
    conn.commit()
    yield conn
    conn.execute("DELETE FROM psn_games WHERE npwr_id = ?", (NPWR,))
    conn.commit()
    conn.close()


def _row(conn):
    r = conn.execute("SELECT * FROM psn_games WHERE npwr_id = ? AND user_id = 1",
                     (NPWR,)).fetchone()
    return {k: r[k] for k in STORED}


def _sync_one(monkeypatch, admin_test_client, title):
    import routes.trophies as trophies
    fake = SimpleNamespace(me=lambda: SimpleNamespace(trophy_titles=lambda: [title]))
    monkeypatch.setattr(trophies, 'get_psn_client', lambda: (fake, None))
    client, csrf = admin_test_client()
    return client.post(f'/api/psn/sync/{NPWR}', headers={'X-CSRF-Token': csrf})


def test_single_sync_keeps_counts_when_blocks_missing(db, monkeypatch, admin_test_client):
    resp = _sync_one(monkeypatch, admin_test_client, _title())
    assert _row(db) == STORED
    body = resp.get_json()
    assert (body['progress'], body['earned'], body['total']) == (50, 10, 20)


def test_single_sync_still_writes_real_counts(db, monkeypatch, admin_test_client):
    _sync_one(monkeypatch, admin_test_client,
              _title(_counts(1, 3, 5, 7), _counts(1, 4, 6, 9)))
    row = _row(db)
    assert row['earned_gold'] == 3 and row['earned_trophies'] == 16
    assert row['progress'] == 80


def test_full_sync_upsert_keeps_counts_when_blocks_missing(db):
    from routes.trophies import _upsert_psn_title
    _upsert_psn_title(db, 1, _title(), 'PS4', None, None)
    assert _row(db) == STORED


def test_full_sync_upsert_inserts_zeros_for_a_new_title(db):
    from routes.trophies import _upsert_psn_title
    db.execute("DELETE FROM psn_games WHERE npwr_id = ?", (NPWR,))
    _upsert_psn_title(db, 1, _title(), 'PS4', None, None)
    assert set(_row(db).values()) == {0}
