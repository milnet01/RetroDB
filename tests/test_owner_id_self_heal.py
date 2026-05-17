"""Regression tests for Pass 30.1 — `_backfill_null_owner_ids(cursor, admin_id)`
is the idempotent startup self-heal that patches up installs already bitten
by the pre-fix migration order bug (tags/lists/wishlist/psn_sync_status rows
left with NULL owner_id because migrations 005/006 couldn't see the admin
row at backfill time).

Runs every startup; WHERE <column> IS NULL makes it a no-op on healthy DBs.
"""

import contextlib
import sqlite3

from services.database_init import _backfill_null_owner_ids


def _make_cursor_with_tables(**rows):
    """Build an in-memory DB with the subset of collection tables relevant
    to the self-heal and seed the given rows."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript("""
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT, owner_id INTEGER);
        CREATE TABLE lists (id INTEGER PRIMARY KEY, name TEXT, owner_id INTEGER);
        CREATE TABLE wishlist (id INTEGER PRIMARY KEY, title TEXT, owner_id INTEGER);
        CREATE TABLE psn_sync_status (id INTEGER PRIMARY KEY, user_id INTEGER);
    """)
    for table, entries in rows.items():
        for entry in entries:
            cols = ', '.join(entry.keys())
            placeholders = ', '.join(['?'] * len(entry))
            conn.execute(
                f"INSERT INTO {table} ({cols}) VALUES ({placeholders})",
                tuple(entry.values()),
            )
    conn.commit()
    return conn


def test_backfills_null_owner_ids_across_all_collection_tables():
    with contextlib.closing(_make_cursor_with_tables(
        tags=[{'name': 'Favourites', 'owner_id': None}, {'name': 'Played', 'owner_id': 7}],
        lists=[{'name': 'Backlog', 'owner_id': None}],
        wishlist=[{'title': 'FFXVI', 'owner_id': None}],
        psn_sync_status=[{'user_id': None}],
    )) as conn:
        cursor = conn.cursor()

        _backfill_null_owner_ids(cursor, admin_id=1)
        conn.commit()

        assert cursor.execute("SELECT owner_id FROM tags WHERE name='Favourites'").fetchone()[0] == 1
        # Existing non-NULL owner preserved.
        assert cursor.execute("SELECT owner_id FROM tags WHERE name='Played'").fetchone()[0] == 7
        assert cursor.execute("SELECT owner_id FROM lists WHERE name='Backlog'").fetchone()[0] == 1
        assert cursor.execute("SELECT owner_id FROM wishlist WHERE title='FFXVI'").fetchone()[0] == 1
        assert cursor.execute("SELECT user_id FROM psn_sync_status").fetchone()[0] == 1


def test_is_idempotent_noop_on_healthy_db():
    with contextlib.closing(_make_cursor_with_tables(
        tags=[{'name': 'a', 'owner_id': 1}, {'name': 'b', 'owner_id': 2}],
    )) as conn:
        cursor = conn.cursor()

        _backfill_null_owner_ids(cursor, admin_id=1)
        _backfill_null_owner_ids(cursor, admin_id=1)
        conn.commit()

        rows = cursor.execute("SELECT name, owner_id FROM tags ORDER BY name").fetchall()
        assert [(r[0], r[1]) for r in rows] == [('a', 1), ('b', 2)]


def test_skips_tables_that_do_not_exist():
    # A DB that never ran migration 005 (no tags/lists/wishlist owner_id
    # column) must not raise — the self-heal must degrade cleanly.
    with contextlib.closing(sqlite3.connect(':memory:')) as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE games (id INTEGER PRIMARY KEY)")

        _backfill_null_owner_ids(cursor, admin_id=1)  # Should not raise


def test_skips_tables_without_expected_column():
    # A DB where `tags` exists but pre-dates migration 005 (no owner_id).
    with contextlib.closing(sqlite3.connect(':memory:')) as conn:
        cursor = conn.cursor()
        cursor.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT)")
        cursor.execute("INSERT INTO tags (name) VALUES ('x')")
        conn.commit()

        _backfill_null_owner_ids(cursor, admin_id=1)  # Should not raise

        # Row untouched, no owner_id column added.
        cols = {r[1] for r in cursor.execute("PRAGMA table_info(tags)")}
        assert 'owner_id' not in cols
