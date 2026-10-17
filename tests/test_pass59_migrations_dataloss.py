"""PASS-59-60 — three landed migrations discarded rows on a state their
siblings raise on.

  (a) 008 dropped a populated `collector_trophies` when no admin existed:
      the row count was never taken, so the copy was skipped and the table
      dropped. Sibling 009 raises on the same state.
  (b) 009's steam / xbox rebuilds copied the old table's whole column list,
      so a legacy table carrying an extra column failed the INSERT with
      "no such column" and Flask could never boot. The game_achievement_progress
      rebuild already intersected with the new shape.
  (c) 011 skipped its copy when a parent table was missing but still ran
      DROP TABLE, discarding every row.

Each test hand-builds the pre-migration state and drives the single migration
through the runner's own transaction shape (BEGIN IMMEDIATE / apply / COMMIT,
ROLLBACK on error), so a raise must leave the rows where they were.
"""

import importlib

import pytest

from tests._util import open_db_positional as _open


def _load(name):
    return importlib.import_module(f'services.migrations.scripts.{name}')


def _run(conn, name):
    """Mirror `services.migrations.apply_pending` for one migration."""
    module = _load(name)
    try:
        conn.execute("BEGIN IMMEDIATE")
        module.apply(conn)
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def _seed_admin(conn):
    conn.execute(
        "CREATE TABLE users (id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "username TEXT, role TEXT NOT NULL DEFAULT 'viewer')"
    )
    conn.execute("INSERT INTO users (username, role) VALUES ('admin', 'admin')")
    conn.commit()
    return conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()[0]


# ---------------------------------------------------------------------------
# (a) 008 — populated collector_trophies, no admin to backfill to
# ---------------------------------------------------------------------------

def test_008_populated_table_without_admin_raises_and_keeps_rows(tmp_path):
    conn = _open(str(tmp_path / 'm008.db'))
    try:
        conn.execute("""
            CREATE TABLE collector_trophies (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                icon TEXT NOT NULL,
                tier TEXT NOT NULL DEFAULT 'bronze',
                category TEXT NOT NULL DEFAULT 'general',
                threshold INTEGER DEFAULT 0,
                earned_at TEXT,
                progress INTEGER DEFAULT 0
            )
        """)
        conn.execute(
            "INSERT INTO collector_trophies (id, name, icon, earned_at) "
            "VALUES ('first_game', 'First Game', 'x.svg', '2025-01-01')"
        )
        conn.commit()

        with pytest.raises(RuntimeError, match='collector_trophies has rows'):
            _run(conn, '008_collector_trophies_user_id')

        rows = conn.execute(
            "SELECT id, earned_at FROM collector_trophies"
        ).fetchall()
        assert rows == [('first_game', '2025-01-01')]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# (b) 009 — legacy steam / xbox tables carrying a column the new DDL lacks
# ---------------------------------------------------------------------------

def test_009_legacy_extra_column_rebuilds_and_keeps_rows(tmp_path):
    conn = _open(str(tmp_path / 'm009.db'))
    try:
        admin_id = _seed_admin(conn)
        conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT)")
        conn.execute("INSERT INTO games (id, title) VALUES (100, 'G')")
        conn.execute("""
            CREATE TABLE steam_achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                apiname TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                icon_url TEXT,
                icon_locked_url TEXT,
                achieved INTEGER DEFAULT 0,
                unlock_time INTEGER DEFAULT 0,
                legacy_rarity REAL
            )
        """)
        conn.execute("""
            CREATE TABLE xbox_achievements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                game_id INTEGER NOT NULL,
                achievement_id TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                icon_url TEXT,
                icon_locked_url TEXT,
                gamerscore INTEGER DEFAULT 0,
                achieved INTEGER DEFAULT 0,
                unlock_time TEXT,
                legacy_rarity REAL
            )
        """)
        conn.execute(
            "INSERT INTO steam_achievements (game_id, apiname, name, achieved, "
            "legacy_rarity) VALUES (100, 'ACH_1', 'One', 1, 0.5)"
        )
        conn.execute(
            "INSERT INTO xbox_achievements (game_id, achievement_id, name, "
            "gamerscore, legacy_rarity) VALUES (100, '7', 'Seven', 50, 0.5)"
        )
        conn.commit()

        _run(conn, '009_achievement_tables_user_id')

        assert conn.execute(
            "SELECT apiname, achieved, user_id FROM steam_achievements"
        ).fetchall() == [('ACH_1', 1, admin_id)]
        assert conn.execute(
            "SELECT achievement_id, gamerscore, user_id FROM xbox_achievements"
        ).fetchall() == [('7', 50, admin_id)]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# (c) 011 — populated user_game_views, parent-table guard false
# ---------------------------------------------------------------------------

def test_011_populated_table_without_parents_raises_and_keeps_rows(tmp_path):
    conn = _open(str(tmp_path / 'm011.db'))
    try:
        # No `games` table: the copy's INNER JOIN cannot run.
        _seed_admin(conn)
        conn.execute("""
            CREATE TABLE user_game_views (
                user_id INTEGER NOT NULL,
                game_id INTEGER NOT NULL,
                last_viewed TEXT NOT NULL,
                PRIMARY KEY (user_id, game_id)
            )
        """)
        conn.execute(
            "INSERT INTO user_game_views VALUES (1, 100, '2025-01-01T00:00:00')"
        )
        conn.commit()

        with pytest.raises(RuntimeError, match='user_game_views has rows'):
            _run(conn, '011_user_game_views_cascade_fk')

        assert conn.execute(
            "SELECT user_id, game_id FROM user_game_views"
        ).fetchall() == [(1, 100)]
    finally:
        conn.close()
