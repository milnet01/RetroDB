"""Tests for Pass 31 multi-user data ownership migrations.

Verifies migrations 007, 008, 009 reshape their target tables correctly:
  * psn_games / psn_trophies rebuild from UNIQUE(npwr_id) to
    UNIQUE(npwr_id, user_id) with legacy rows backfilled to admin
  * collector_trophies rebuild with (id, user_id) composite PK
  * game_achievement_progress / steam_achievements / xbox_achievements
    pick up user_id with legacy rows backfilled to admin
"""

import sqlite3

import pytest

from services import migrations


def _open(path):
    # NOTE: a near-twin exists in tests/test_migrations.py without the
    # `row_factory = sqlite3.Row` line. Kept separate intentionally —
    # this file's tests use name access (row['col']), the other uses
    # positional (row[0]). Don't merge without auditing both call
    # patterns.
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


@pytest.fixture
def migrated_db(tmp_path):
    """A fully-migrated, empty SQLite connection.

    Replaces the open/migrate/close scaffold repeated across this file
    (test-audit DUP-2). Tests that need pre-migration state (like
    `test_legacy_gap_rows_backfill_to_admin`) still drive the partial
    migration inline against their own connection.
    """
    path = str(tmp_path / 'migrated.db')
    conn = _open(path)
    migrations.apply_pending(conn)
    try:
        yield conn
    finally:
        conn.close()


class TestPSNUserIdMigration:
    """Migration 007 — psn_games / psn_trophies user_id (Pass 31.1)."""

    def test_fresh_install_creates_psn_games_with_user_id(self, migrated_db):
        """No pre-existing psn_games — migration 007 creates it with the
        new shape including user_id + UNIQUE(npwr_id, user_id)."""
        cols = {row[1] for row in migrated_db.execute("PRAGMA table_info(psn_games)")}
        assert 'user_id' in cols
        assert 'npwr_id' in cols

        # The unique index must be (npwr_id, user_id), not npwr_id alone.
        indexes = list(migrated_db.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type='index' AND tbl_name='psn_games'"
        ))
        npwr_user = [ix for ix in indexes if 'npwr_user' in ix['name']]
        assert npwr_user, "expected idx_psn_games_npwr_user"
        assert 'user_id' in npwr_user[0]['sql']

    def test_two_users_can_have_same_npwr_id(self, migrated_db):
        """The whole point of Pass 31.1 — two users with the same game sync
        each get their own row, no more cross-user clobbering.

        We don't seed a `users` table here — psn_games.user_id is a bare
        INTEGER, not a FK to users(id), so the test cares only about the
        composite UNIQUE(npwr_id, user_id) shape on psn_games. The
        previous version created a redundant users table with
        `IF NOT EXISTS`, which would have masked a regression where the
        migration silently failed to create the table (test-audit
        FIXTURE finding)."""
        migrated_db.execute(
            "INSERT INTO psn_games (npwr_id, user_id, title, earned_bronze) VALUES (?, ?, ?, ?)",
            ('NPWR12345', 1, 'The Same Game', 5),
        )
        migrated_db.execute(
            "INSERT INTO psn_games (npwr_id, user_id, title, earned_bronze) VALUES (?, ?, ?, ?)",
            ('NPWR12345', 2, 'The Same Game', 10),
        )
        migrated_db.commit()

        rows = migrated_db.execute(
            "SELECT user_id, earned_bronze FROM psn_games WHERE npwr_id = 'NPWR12345' "
            "ORDER BY user_id"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]['earned_bronze'] == 5
        assert rows[1]['earned_bronze'] == 10


class TestCollectorTrophiesUserIdMigration:
    """Migration 008 — collector_trophies (id, user_id) composite (Pass 31.3)."""

    def test_fresh_install_has_user_id_column(self, migrated_db):
        """Fresh migration adds user_id column to collector_trophies so
        every trophy row is owned by a specific user (Pass 31.3)."""
        cols = {row[1] for row in migrated_db.execute(
            "PRAGMA table_info(collector_trophies)"
        )}
        assert 'user_id' in cols

    def test_two_users_can_earn_same_trophy(self, migrated_db):
        """Composite primary key (id, user_id) lets two users independently
        earn the same trophy id — no cross-user clobbering (Pass 31.3)."""
        migrated_db.execute(
            "INSERT INTO collector_trophies (id, user_id, name, icon, tier) "
            "VALUES ('first_game', 1, 'First Steps', 'icon', 'bronze')"
        )
        migrated_db.execute(
            "INSERT INTO collector_trophies (id, user_id, name, icon, tier) "
            "VALUES ('first_game', 2, 'First Steps', 'icon', 'bronze')"
        )
        migrated_db.commit()

        count = migrated_db.execute(
            "SELECT COUNT(*) FROM collector_trophies WHERE id = 'first_game'"
        ).fetchone()[0]
        assert count == 2


class TestAchievementUserIdMigration:
    """Migration 009 — game_achievement_progress / steam_achievements /
    xbox_achievements per user (Pass 31.2)."""

    def test_fresh_install_has_user_id_on_all_three(self, migrated_db):
        for table in ('game_achievement_progress', 'steam_achievements', 'xbox_achievements'):
            cols = {row[1] for row in migrated_db.execute(f"PRAGMA table_info({table})")}
            assert 'user_id' in cols, f"{table} missing user_id after migration 009"

    def test_two_users_steam_achievements_coexist(self, migrated_db):
        migrated_db.execute(
            "INSERT INTO steam_achievements (game_id, user_id, apiname, name, achieved) "
            "VALUES (100, 1, 'ACH_FIRST_BLOOD', 'First Blood', 0)"
        )
        migrated_db.execute(
            "INSERT INTO steam_achievements (game_id, user_id, apiname, name, achieved) "
            "VALUES (100, 2, 'ACH_FIRST_BLOOD', 'First Blood', 1)"
        )
        migrated_db.commit()

        rows = migrated_db.execute(
            "SELECT user_id, achieved FROM steam_achievements "
            "WHERE game_id = 100 AND apiname = 'ACH_FIRST_BLOOD' ORDER BY user_id"
        ).fetchall()
        assert len(rows) == 2
        assert rows[0]['achieved'] == 0
        assert rows[1]['achieved'] == 1

    def test_legacy_gap_rows_backfill_to_admin(self, tmp_path, monkeypatch):
        """Legacy install path — game_achievement_progress already has rows
        from a pre-31 install. Migration 009 backfills them to the admin.

        Can't use the `migrated_db` fixture here because we need to stop
        partway through the migration chain and seed legacy rows in the
        old shape before letting migration 009 reshape them.
        """
        path = str(tmp_path / 'legacy_gap.db')
        conn = _open(path)
        try:
            admin_id = _seed_admin(conn)

            # Stop after baseline (001) so we can seed gap rows in the old shape,
            # then run 009 as a reshape step. Use monkeypatch (not try/finally)
            # so the global list is restored even if the test is killed
            # mid-run (SIGKILL/OOM) — same rationale as test_migrations.py:324.
            real_list = migrations.MIGRATIONS
            monkeypatch.setattr(migrations, 'MIGRATIONS', real_list[:4])  # 001..004 — gap table exists
            migrations.apply_pending(conn)
            monkeypatch.setattr(migrations, 'MIGRATIONS', real_list)

            # Pass 45.10 — migration 009 now runs PRAGMA foreign_key_check
            # before commit. Migration 009 adds FOREIGN KEY(game_id)
            # REFERENCES games(id) on game_achievement_progress; we have to
            # seed a parent games row so the check passes. Pre-45.10 the
            # legacy gap row referenced a non-existent game_id and the
            # rebuild silently kept the dangling reference.
            conn.execute(
                "INSERT INTO games (id, title, system_id, rom_path) "
                "VALUES (?, ?, ?, ?)",
                (100, 'Legacy Gap Test Game', 1,
                 str(tmp_path / 'legacy_gap_test.rom')),
            )
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
            assert row['user_id'] == admin_id
            assert row['earned_achievements'] == 5
        finally:
            conn.close()
