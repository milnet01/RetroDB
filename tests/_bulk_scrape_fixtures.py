"""Shared bulk-scrape test fixtures.

Extracted during the 2026-05-18 test-audit fix-pass (c-001 MED): the
`_make_memory_db()` helper plus the 7-line `patch.object(bulk_scrape_mod, ...)`
stanza were duplicated verbatim across `test_bulk_scrape_job.py::job` and
`test_bulk_scrape_race.py::job_with_real_thread`. Centralising here means a
new persistence helper in `services.jobs.bulk_scrape` only needs one
update site.
"""

from __future__ import annotations

import contextlib
import sqlite3
from unittest.mock import patch


def make_memory_db():
    """Build a minimal in-memory DB the job's `start()` can query for
    system/game titles. Shared fixture content."""
    conn = sqlite3.connect(':memory:', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, system_id INTEGER);
        INSERT INTO systems (id, name) VALUES (1, 'NES'), (2, 'SNES');
        INSERT INTO games (id, title, system_id) VALUES
            (100, 'Super Mario Bros', 1),
            (101, 'Zelda', 1),
            (200, 'F-Zero', 2);
    """)
    return conn


@contextlib.contextmanager
def bulk_scrape_persistence_patches(mem_db):
    """Yield with every bulk_scrape persistence helper + the singleton lock
    stubbed to a no-op. The sentinel `acquire_job_singleton_lock=0`
    matches the documented "acquired, no real lock" path so the matching
    `release_job_singleton_lock(0)` in production code is a documented
    no-op.

    Mirrors the 7-line stanza that was inlined in two test fixtures
    pre-fix-pass. Add new patches here when bulk_scrape grows a new
    persistence helper rather than editing two call sites.
    """
    from services.jobs import bulk_scrape as bulk_scrape_mod
    with patch.object(bulk_scrape_mod, '_get_conn', return_value=mem_db), \
         patch.object(bulk_scrape_mod, 'persist_job_start', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_progress', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_complete', return_value=None), \
         patch.object(bulk_scrape_mod, 'persist_job_queued', return_value=999), \
         patch.object(bulk_scrape_mod, 'remove_queued_job', return_value=None), \
         patch.object(bulk_scrape_mod, 'acquire_job_singleton_lock', return_value=0):
        yield bulk_scrape_mod
