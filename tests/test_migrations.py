"""Tests for services.migrations — Pass 20.1.

Verifies the PRAGMA user_version-driven migration runner:
  * fresh DB advances from 0 -> latest_version() and creates schema
  * a "legacy" install (pre-seeded schema, user_version still 0) finishes at
    latest_version() without erroring on already-existing tables/columns
  * apply_pending is a no-op once user_version == latest_version()
  * a migration that raises rolls back AND leaves user_version untouched
  * a DB ahead of the build refuses to run
"""

import os
import sqlite3
import tempfile

import pytest

from services import migrations


def _open(path):
    return sqlite3.connect(path)


def _seed_legacy(path):
    """Build the schema the way pre-v2.91 init_database() did, leaving
    user_version=0 (the value SQLite ships)."""
    conn = _open(path)
    c = conn.cursor()
    c.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT, folder TEXT UNIQUE, logo TEXT)")
    c.execute("""
        CREATE TABLE games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            genre TEXT,
            pegi_rating TEXT,
            rom_path TEXT NOT NULL UNIQUE
        )
    """)
    # Insert a row with the *old* genre format so we can verify migration 002
    # actually rewrites it.
    c.execute("INSERT INTO systems (name, folder) VALUES ('PS1', 'ps1')")
    c.execute(
        "INSERT INTO games (system_id, title, genre, pegi_rating, rom_path) "
        "VALUES (1, 'Test', 'FPS,Action', '12', 'ps1/test.bin')"
    )
    conn.commit()
    conn.close()


class TestApplyPending:
    def test_fresh_db_runs_all_migrations(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'fresh.db')
            conn = _open(path)
            assert migrations.current_version(conn) == 0

            applied = migrations.apply_pending(conn)
            conn.close()

            # Verify every declared migration ran
            assert applied == list(range(1, migrations.latest_version() + 1))

            # Verify schema exists + version persisted to disk
            conn = _open(path)
            assert migrations.current_version(conn) == migrations.latest_version()
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            for required in ('systems', 'games', 'job_queue', 'tags', 'wishlist'):
                assert required in tables, f"missing table: {required}"
            conn.close()

    def test_legacy_install_advances_without_errors(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'legacy.db')
            _seed_legacy(path)

            conn = _open(path)
            assert migrations.current_version(conn) == 0
            applied = migrations.apply_pending(conn)
            conn.close()

            assert applied == list(range(1, migrations.latest_version() + 1))

            # Pre-seeded row's data migrations must have run: 'FPS' -> hyphenated form
            # and bare '12' -> 'PEGI 12'.
            conn = _open(path)
            row = conn.execute("SELECT genre, pegi_rating FROM games WHERE title = 'Test'").fetchone()
            conn.close()
            assert 'First-Person-Shooter' in row[0]
            assert row[1] == 'PEGI 12'

    def test_noop_when_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'fresh.db')
            conn = _open(path)
            migrations.apply_pending(conn)
            conn.close()

            conn = _open(path)
            applied = migrations.apply_pending(conn)
            conn.close()
            assert applied == []

    def test_failed_migration_rolls_back_and_keeps_version(self, monkeypatch):
        """If a migration raises, user_version must NOT advance and any partial
        DDL must roll back."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'fail.db')
            conn = _open(path)

            # Inject a synthetic "004" migration that creates a table then crashes.
            class BoomModule:
                @staticmethod
                def apply(conn):
                    conn.execute("CREATE TABLE boom_marker (id INTEGER)")
                    raise RuntimeError("simulated migration failure")

            real_load = migrations._load
            real_list = migrations.MIGRATIONS

            def fake_load(name):
                if name == '004_boom':
                    return BoomModule
                return real_load(name)

            monkeypatch.setattr(migrations, '_load', fake_load)
            monkeypatch.setattr(migrations, 'MIGRATIONS', real_list + ['004_boom'])

            with pytest.raises(RuntimeError, match="simulated"):
                migrations.apply_pending(conn)
            conn.close()

            conn = _open(path)
            # latest_version() now reports 4 because we patched MIGRATIONS, but
            # the DB should be stuck at 3 (the last migration that succeeded).
            assert migrations.current_version(conn) == len(real_list)
            tables = {
                row[0]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
            assert 'boom_marker' not in tables
            conn.close()

    def test_db_ahead_of_build_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'future.db')
            conn = _open(path)
            future = migrations.latest_version() + 5
            conn.execute(f"PRAGMA user_version = {future}")
            conn.commit()

            with pytest.raises(RuntimeError, match="newer than"):
                migrations.apply_pending(conn)
            conn.close()

    def test_idempotent_baseline_can_run_twice(self):
        """Sanity check that running 001 against an already-migrated DB is a
        no-op — protects against future edits to 001 that break legacy
        compatibility."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'fresh.db')
            conn = _open(path)
            migrations.apply_pending(conn)
            # Now force version back to 0 and rerun — should not raise on
            # existing tables.
            conn.execute("PRAGMA user_version = 0")
            conn.commit()
            applied = migrations.apply_pending(conn)
            conn.close()
            assert applied == list(range(1, migrations.latest_version() + 1))


class TestUpdatedAtTriggers:
    """Migration 004 adds games.updated_at + INSERT/UPDATE triggers — the
    Pass 21 ETag scheme depends on MAX(updated_at) being fresh without each
    write-site having to remember to stamp it."""

    def test_insert_stamps_updated_at(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'ins.db')
            conn = _open(path)
            migrations.apply_pending(conn)
            conn.execute("INSERT INTO systems (name, folder) VALUES ('PS1', 'ps1')")
            conn.execute(
                "INSERT INTO games (system_id, title, rom_path) "
                "VALUES (1, 'Test', 'ps1/test.bin')"
            )
            conn.commit()
            row = conn.execute("SELECT updated_at FROM games").fetchone()
            conn.close()
            assert row[0] is not None and row[0].endswith('Z')

    def test_update_refreshes_updated_at(self):
        import time
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'upd.db')
            conn = _open(path)
            migrations.apply_pending(conn)
            conn.execute("INSERT INTO systems (name, folder) VALUES ('PS1', 'ps1')")
            conn.execute(
                "INSERT INTO games (system_id, title, rom_path) "
                "VALUES (1, 'Test', 'ps1/test.bin')"
            )
            conn.commit()
            first = conn.execute("SELECT id, updated_at FROM games").fetchone()
            time.sleep(0.01)
            conn.execute("UPDATE games SET title = 'Renamed' WHERE id = ?", (first[0],))
            conn.commit()
            second = conn.execute("SELECT updated_at FROM games WHERE id = ?", (first[0],)).fetchone()
            conn.close()
            assert second[0] > first[1], \
                f"updated_at did not advance: before={first[1]!r} after={second[0]!r}"

    def test_legacy_rows_backfilled(self):
        """Rows present before the column was added should come out with a
        non-NULL updated_at."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'legacy.db')
            _seed_legacy(path)
            conn = _open(path)
            migrations.apply_pending(conn)
            row = conn.execute("SELECT updated_at FROM games WHERE title = 'Test'").fetchone()
            conn.close()
            assert row[0] is not None


class TestVersionHelpers:
    def test_latest_matches_migrations_length(self):
        assert migrations.latest_version() == len(migrations.MIGRATIONS)

    def test_current_version_default_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'empty.db')
            conn = _open(path)
            assert migrations.current_version(conn) == 0
            conn.close()


class TestCollectionsOwnerId:
    """Migration 005 adds owner_id to tags/lists/wishlist (Pass 27.1).

    Verifies (a) the column lands on a fresh install, (b) legacy rows that
    pre-date the column get backfilled to the first admin's user_id, and
    (c) the per-table owner_id index exists.
    """

    def test_fresh_install_adds_column_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'fresh.db')
            conn = _open(path)
            migrations.apply_pending(conn)

            for table in ('tags', 'lists', 'wishlist'):
                cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                assert 'owner_id' in cols, f"{table}.owner_id missing"

                indexes = {
                    row[0] for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name=?",
                        (table,),
                    )
                }
                assert f'idx_{table}_owner_id' in indexes, \
                    f"missing owner_id index on {table}"
            conn.close()

    def test_backfill_assigns_legacy_rows_to_admin(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'backfill.db')

            # Hand-build a "pre-Pass-27" install: tags/lists/wishlist exist
            # via baseline 001 but without owner_id, and a users table with
            # one admin already exists (since real installs always run
            # ensure_user_tables() on first launch).
            conn = _open(path)
            conn.execute("""
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    role TEXT NOT NULL DEFAULT 'viewer'
                )
            """)
            conn.execute("INSERT INTO users (username, role) VALUES ('admin', 'admin')")
            admin_id = conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()[0]
            conn.commit()

            # Stop migrations after 001 so we can seed legacy rows without
            # owner_id, then re-run apply_pending to land 005.
            real_list = migrations.MIGRATIONS
            try:
                migrations.MIGRATIONS = real_list[:1]  # only 001_baseline
                migrations.apply_pending(conn)
            finally:
                migrations.MIGRATIONS = real_list

            conn.execute("INSERT INTO tags (name) VALUES ('legacy_tag')")
            conn.execute("INSERT INTO lists (name) VALUES ('legacy_list')")
            conn.execute("INSERT INTO wishlist (title) VALUES ('legacy_game')")
            conn.commit()

            # Now run the rest of the migrations including 005.
            migrations.apply_pending(conn)

            for table in ('tags', 'lists', 'wishlist'):
                row = conn.execute(f"SELECT owner_id FROM {table}").fetchone()
                assert row[0] == admin_id, \
                    f"{table}.owner_id not backfilled to admin (got {row[0]!r})"
            conn.close()

    def test_no_users_table_skips_backfill(self):
        """Truly fresh install: users table doesn't exist yet at migration
        time (ensure_user_tables runs after init_database). Migration must
        not error and must not create rows that aren't there."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'no_users.db')
            conn = _open(path)
            # Should run all migrations without raising.
            applied = migrations.apply_pending(conn)
            assert 5 in applied
            assert conn.execute("SELECT COUNT(*) FROM tags").fetchone()[0] == 0
            conn.close()
