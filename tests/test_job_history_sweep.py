"""Tests for services.jobs.base.sweep_old_job_history — Pass 19.6."""

import os
import sqlite3
import tempfile
from unittest.mock import patch

import pytest

from services.jobs import base as base_mod


def _make_file_db():
    """Real file-backed DB — sweep_old_job_history closes its connection in
    `finally`, so an in-memory DB would be discarded between assertions."""
    tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
    tmp.close()
    conn = sqlite3.connect(tmp.name)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE job_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            status TEXT DEFAULT 'running',
            progress TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            error_message TEXT,
            params TEXT
        );
    """)
    conn.commit()
    return conn, tmp.name


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _insert_job(conn, status, completed_days_ago, job_type='bulk_scrape'):
    completed_at = (
        f"datetime('now', '-{completed_days_ago} days')"
        if completed_days_ago is not None else "NULL"
    )
    sql = f"""
        INSERT INTO job_queue
            (job_type, status, progress, created_at, updated_at, completed_at)
        VALUES
            (?, ?, '{{}}', datetime('now', '-{(completed_days_ago or 0) + 1} days'),
             datetime('now'), {completed_at})
    """
    conn.execute(sql, (job_type, status))
    conn.commit()


@pytest.fixture
def db_path():
    conn, path = _make_file_db()
    conn.close()

    def _fresh_conn():
        return _open(path)

    with patch.object(base_mod, '_get_conn', side_effect=_fresh_conn):
        yield path

    try:
        os.remove(path)
    except OSError:
        pass


class TestSweepOldJobHistory:
    def test_prunes_terminal_rows_older_than_retention(self, db_path):
        conn = _open(db_path)
        try:
            _insert_job(conn, 'completed', 60)
            _insert_job(conn, 'failed', 45)
            _insert_job(conn, 'dismissed', 35)
            _insert_job(conn, 'cancelled', 31)
            _insert_job(conn, 'completed', 29)  # inside window
        finally:
            conn.close()

        deleted = base_mod.sweep_old_job_history(retention_days=30)

        assert deleted == 4
        verify = _open(db_path)
        try:
            remaining = verify.execute("SELECT status FROM job_queue").fetchall()
        finally:
            verify.close()
        assert len(remaining) == 1
        assert remaining[0]['status'] == 'completed'

    def test_never_prunes_active_states(self, db_path):
        """Running / queued / interrupted rows stay even if ancient."""
        conn = _open(db_path)
        try:
            _insert_job(conn, 'running', 365)
            _insert_job(conn, 'queued', 365)
            _insert_job(conn, 'interrupted', 365)
        finally:
            conn.close()

        deleted = base_mod.sweep_old_job_history(retention_days=30)

        assert deleted == 0
        verify = _open(db_path)
        try:
            assert verify.execute("SELECT COUNT(*) FROM job_queue").fetchone()[0] == 3
        finally:
            verify.close()

    def test_retention_zero_disables_sweep(self, db_path):
        conn = _open(db_path)
        try:
            _insert_job(conn, 'completed', 365)
        finally:
            conn.close()

        assert base_mod.sweep_old_job_history(retention_days=0) == 0

        verify = _open(db_path)
        try:
            assert verify.execute("SELECT COUNT(*) FROM job_queue").fetchone()[0] == 1
        finally:
            verify.close()

    def test_retention_negative_disables_sweep(self, db_path):
        conn = _open(db_path)
        try:
            _insert_job(conn, 'completed', 365)
        finally:
            conn.close()

        assert base_mod.sweep_old_job_history(retention_days=-1) == 0

    def test_missing_completed_at_is_not_pruned(self, db_path):
        """A terminal row without a completed_at (older data before the
        column was populated) shouldn't be swept — we can't know its age."""
        conn = _open(db_path)
        try:
            _insert_job(conn, 'completed', None)
        finally:
            conn.close()

        assert base_mod.sweep_old_job_history(retention_days=30) == 0

        verify = _open(db_path)
        try:
            assert verify.execute("SELECT COUNT(*) FROM job_queue").fetchone()[0] == 1
        finally:
            verify.close()
