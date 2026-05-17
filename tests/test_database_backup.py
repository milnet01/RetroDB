"""Tests for services.database.backup_database — the SQLite online-backup
helper introduced in Pass 19.1 to replace `shutil.copy2(DB)`."""

import os
import sqlite3
import tempfile

import pytest

from services.database import backup_database


def _populate(path, rows=10):
    conn = sqlite3.connect(path)
    try:
        conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        conn.executemany("INSERT INTO t (val) VALUES (?)", [(f"row-{i}",) for i in range(rows)])
        conn.commit()
    finally:
        conn.close()


class TestBackupDatabase:
    def test_backup_creates_consistent_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src.db')
            dst = os.path.join(tmp, 'dst.db')
            _populate(src, rows=25)

            backup_database(src, dst)

            assert os.path.exists(dst)
            verify = sqlite3.connect(dst)
            try:
                count = verify.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            finally:
                verify.close()
            assert count == 25

    def test_backup_works_under_wal_mode(self):
        """The whole point of switching from shutil.copy2 → backup API is
        WAL safety. Verify WAL-mode source still produces a usable backup."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src.db')
            dst = os.path.join(tmp, 'dst.db')

            conn = sqlite3.connect(src)
            try:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
                conn.executemany("INSERT INTO t (val) VALUES (?)", [(f"row-{i}",) for i in range(10)])
                conn.commit()
            finally:
                conn.close()

            backup_database(src, dst)

            verify = sqlite3.connect(dst)
            try:
                count = verify.execute("SELECT COUNT(*) FROM t").fetchone()[0]
            finally:
                verify.close()
            assert count == 10

    def test_backup_with_concurrent_open_writer(self):
        """Source connection still open with uncommitted writes during the
        backup — backup should still succeed and reflect committed state."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src.db')
            dst = os.path.join(tmp, 'dst.db')
            _populate(src, rows=5)

            holder = sqlite3.connect(src)
            try:
                holder.execute("PRAGMA journal_mode=WAL")
                # Write some uncommitted rows; they must NOT appear in backup.
                holder.execute("INSERT INTO t (val) VALUES ('uncommitted')")

                backup_database(src, dst)

                verify = sqlite3.connect(dst)
                try:
                    rows = verify.execute("SELECT val FROM t").fetchall()
                finally:
                    verify.close()
                vals = [r[0] for r in rows]
                assert 'uncommitted' not in vals
                assert len(vals) == 5
            finally:
                holder.rollback()
                holder.close()

    def test_backup_corrupt_destination_is_removed(self, monkeypatch):
        """If the verify step finds the destination corrupt, the helper
        must delete the partial file and raise — never hand back a broken
        backup. We simulate the failure by stubbing the verify connection
        with a fake that returns a non-`ok` PRAGMA result."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src.db')
            dst = os.path.join(tmp, 'dst.db')
            _populate(src)

            import services.database as db_mod
            real_connect = db_mod.sqlite3.connect

            class _FakeCursor:
                def fetchone(self):
                    return ('database disk image is malformed',)

            class _FakeVerifyConn:
                def execute(self, sql):
                    # Pass 45.10 — the verify connection now also issues
                    # `PRAGMA busy_timeout = 5000` before the integrity
                    # check; both must be tolerated by the fake.
                    sql_lower = sql.lower()
                    assert (
                        'integrity_check' in sql_lower
                        or 'busy_timeout' in sql_lower
                    )
                    if 'busy_timeout' in sql_lower:
                        return _FakeCursor()  # ignored result
                    return _FakeCursor()

                def close(self):
                    pass

            calls = {'n': 0}

            def fake_connect(path, *args, **kwargs):
                calls['n'] += 1
                # 1st: src; 2nd: dst (real backup target); 3rd: verify (fake).
                if calls['n'] == 3:
                    return _FakeVerifyConn()
                return real_connect(path, *args, **kwargs)

            # `monkeypatch.setattr` restores the original automatically even
            # if an assertion below raises — no manual try/finally needed.
            monkeypatch.setattr(db_mod.sqlite3, 'connect', fake_connect)
            with pytest.raises(RuntimeError, match='integrity check'):
                backup_database(src, dst)
            assert not os.path.exists(dst), \
                "corrupt backup file must be removed after integrity check fails"

    def test_backup_missing_destination_dir(self):
        """Pin the contract for a destination whose parent directory does
        not exist. `backup_database` opens a sqlite3 connection on dst,
        which surfaces `sqlite3.OperationalError: unable to open database
        file` rather than silently creating the directory."""
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, 'src.db')
            dst = os.path.join(tmp, 'subdir', 'dst.db')  # subdir never created
            _populate(src)

            with pytest.raises(sqlite3.OperationalError):
                backup_database(src, dst)

            assert not os.path.exists(dst), \
                "no backup file should remain when the destination dir is missing"
