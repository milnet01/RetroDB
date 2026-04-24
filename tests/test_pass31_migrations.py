"""Tests for Pass 31 multi-user data ownership migrations.

Verifies migrations 007, 008, 009 reshape their target tables correctly:
  * psn_games / psn_trophies rebuild from UNIQUE(npwr_id) to
    UNIQUE(npwr_id, user_id) with legacy rows backfilled to admin
  * collector_trophies rebuild with (id, user_id) composite PK
  * game_achievement_progress / steam_achievements / xbox_achievements
    pick up user_id with legacy rows backfilled to admin
"""

import os
import sqlite3
import tempfile

from services import migrations


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _seed_admin(conn):
    """Create a minimal users table with a single admin. Pass 31 migrations
    look up `SELECT id FROM users WHERE role = 'admin'` during backfill."""
    conn.execute("""
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            role TEXT NOT NULL DEFAULT 'viewer'
        )
    """)
    conn.execute("INSERT INTO users (username, role) VALUES ('admin', 'admin')")
    conn.execute("INSERT INTO users (username, role) VALUES ('editor', 'editor')")
    conn.commit()
    return conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()[0]


class TestPSNUserIdMigration:
    """Migration 007 — psn_games / psn_trophies user_id (Pass 31.1)."""

    def test_fresh_install_creates_psn_games_with_user_id(self):
        """No pre-existing psn_games — migration 007 creates it with the
        new shape including user_id + UNIQUE(npwr_id, user_id)."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'fresh.db')
            conn = _open(path)
            migrations.apply_pending(conn)

            cols = {row[1] for row in conn.execute("PRAGMA table_info(psn_games)")}
            assert 'user_id' in cols
            assert 'npwr_id' in cols

            # The unique index must be (npwr_id, user_id), not npwr_id alone.
            indexes = list(conn.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type='index' AND tbl_name='psn_games'"
            ))
            npwr_user = [ix for ix in indexes if 'npwr_user' in ix['name']]
            assert npwr_user, "expected idx_psn_games_npwr_user"
            assert 'user_id' in npwr_user[0]['sql']
            conn.close()

    def test_two_users_can_have_same_npwr_id(self):
        """The whole point of Pass 31.1 — two users with the same game sync
        each get their own row, no more cross-user clobbering."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'two_users.db')
            conn = _open(path)
            migrations.apply_pending(conn)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT DEFAULT 'admin'
                )
            """)
            conn.executemany("INSERT INTO users (role) VALUES (?)", [('admin',), ('editor',)])

            conn.execute(
                "INSERT INTO psn_games (npwr_id, user_id, title, earned_bronze) VALUES (?, ?, ?, ?)",
                ('NPWR12345', 1, 'The Same Game', 5),
            )
            conn.execute(
                "INSERT INTO psn_games (npwr_id, user_id, title, earned_bronze) VALUES (?, ?, ?, ?)",
                ('NPWR12345', 2, 'The Same Game', 10),
            )
            conn.commit()

            rows = conn.execute(
                "SELECT user_id, earned_bronze FROM psn_games WHERE npwr_id = 'NPWR12345' "
                "ORDER BY user_id"
            ).fetchall()
            conn.close()
            assert len(rows) == 2
            assert rows[0]['earned_bronze'] == 5
            assert rows[1]['earned_bronze'] == 10


class TestCollectorTrophiesUserIdMigration:
    """Migration 008 — collector_trophies (id, user_id) composite (Pass 31.3)."""

    def test_fresh_install_has_user_id_column(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'fresh.db')
            conn = _open(path)
            migrations.apply_pending(conn)

            cols = {row[1] for row in conn.execute("PRAGMA table_info(collector_trophies)")}
            assert 'user_id' in cols
            conn.close()

    def test_two_users_can_earn_same_trophy(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'two_users_trophies.db')
            conn = _open(path)
            migrations.apply_pending(conn)

            conn.execute(
                "INSERT INTO collector_trophies (id, user_id, name, icon, tier) "
                "VALUES ('first_game', 1, 'First Steps', 'icon', 'bronze')"
            )
            conn.execute(
                "INSERT INTO collector_trophies (id, user_id, name, icon, tier) "
                "VALUES ('first_game', 2, 'First Steps', 'icon', 'bronze')"
            )
            conn.commit()

            count = conn.execute(
                "SELECT COUNT(*) FROM collector_trophies WHERE id = 'first_game'"
            ).fetchone()[0]
            conn.close()
            assert count == 2


class TestAchievementUserIdMigration:
    """Migration 009 — game_achievement_progress / steam_achievements /
    xbox_achievements per user (Pass 31.2)."""

    def test_fresh_install_has_user_id_on_all_three(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'fresh.db')
            conn = _open(path)
            migrations.apply_pending(conn)

            for table in ('game_achievement_progress', 'steam_achievements', 'xbox_achievements'):
                cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                assert 'user_id' in cols, f"{table} missing user_id after migration 009"
            conn.close()

    def test_two_users_steam_achievements_coexist(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'steam_coexist.db')
            conn = _open(path)
            migrations.apply_pending(conn)

            conn.execute(
                "INSERT INTO steam_achievements (game_id, user_id, apiname, name, achieved) "
                "VALUES (100, 1, 'ACH_FIRST_BLOOD', 'First Blood', 0)"
            )
            conn.execute(
                "INSERT INTO steam_achievements (game_id, user_id, apiname, name, achieved) "
                "VALUES (100, 2, 'ACH_FIRST_BLOOD', 'First Blood', 1)"
            )
            conn.commit()

            rows = conn.execute(
                "SELECT user_id, achieved FROM steam_achievements "
                "WHERE game_id = 100 AND apiname = 'ACH_FIRST_BLOOD' ORDER BY user_id"
            ).fetchall()
            conn.close()
            assert len(rows) == 2
            assert rows[0]['achieved'] == 0
            assert rows[1]['achieved'] == 1

    def test_legacy_gap_rows_backfill_to_admin(self):
        """Legacy install path — game_achievement_progress already has rows
        from a pre-31 install. Migration 009 backfills them to the admin."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'legacy_gap.db')
            conn = _open(path)
            admin_id = _seed_admin(conn)

            # Stop after baseline (001) so we can seed gap rows in the old shape,
            # then run 009 as a reshape step.
            real = migrations.MIGRATIONS
            try:
                migrations.MIGRATIONS = real[:4]  # 001..004 — gap table exists
                migrations.apply_pending(conn)
            finally:
                migrations.MIGRATIONS = real

            conn.execute(
                "INSERT INTO game_achievement_progress "
                "(game_id, earned_achievements, total_achievements) VALUES (?, ?, ?)",
                (100, 5, 10),
            )
            conn.commit()

            migrations.apply_pending(conn)

            row = conn.execute(
                "SELECT user_id, earned_achievements FROM game_achievement_progress "
                "WHERE game_id = 100"
            ).fetchone()
            conn.close()
            assert row['user_id'] == admin_id
            assert row['earned_achievements'] == 5
