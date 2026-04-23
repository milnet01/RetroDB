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
import sys
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


class TestVersionHelpers:
    def test_latest_matches_migrations_length(self):
        assert migrations.latest_version() == len(migrations.MIGRATIONS)

    def test_current_version_default_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'empty.db')
            conn = _open(path)
            assert migrations.current_version(conn) == 0
            conn.close()
