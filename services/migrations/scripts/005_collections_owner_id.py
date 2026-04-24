# =============================================================================
# Migration 005 — owner_id on tags / lists / wishlist (Pass 27.1)
# =============================================================================
# Per-user data ownership for the collections feature. Pre-Pass 27, every
# logged-in user could see and mutate every other user's tags, lists, and
# wishlist items because the schema had no owner column at all. This adds
# `owner_id INTEGER REFERENCES users(id)` to each, backfills existing rows
# to the first admin user (legacy installs are single-tenant by definition),
# and indexes the new column for the per-user filter that routes/collections.py
# now applies to every read.
#
# Note: the FK reference does not require the `users` table to exist at DDL
# time — SQLite validates FK targets only at INSERT/UPDATE with PRAGMA
# foreign_keys=ON, which RetroDB does not enable. Backfill is guarded so a
# truly fresh install (no users table, no rows to scope) is a no-op.
# =============================================================================

import logging

logger = logging.getLogger(__name__)


def _add_column_if_missing(cursor, table, column, definition):
    cols = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def apply(conn):
    cursor = conn.cursor()

    target_tables = ('tags', 'lists', 'wishlist')

    for table in target_tables:
        exists = cursor.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone() is not None
        if not exists:
            # Migration 001 creates all three; this branch only fires if the
            # baseline migration did not run (impossible in practice — the
            # ordered MIGRATIONS list runs 001 before 005). Stay defensive.
            continue

        _add_column_if_missing(
            cursor, table, 'owner_id', 'INTEGER REFERENCES users(id)'
        )
        cursor.execute(
            f"CREATE INDEX IF NOT EXISTS idx_{table}_owner_id ON {table}(owner_id)"
        )

    # Backfill: legacy rows (created before this migration) get assigned to
    # the first admin user. Single-tenant installs — which is everyone before
    # Pass 24 — collapse cleanly to "admin owns everything", matching the
    # pre-migration behavior where any logged-in user could see/mutate any
    # row.
    users_exists = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
    ).fetchone() is not None
    if not users_exists:
        # Nothing to do — collection tables are either empty (fresh install)
        # or the caller hasn't bootstrapped the users table yet, so there's
        # no admin id to backfill against. Pass 30.1 made this unreachable
        # on the normal init path (ensure_user_tables() now runs before
        # init_database()), but the guard stays as a belt-and-braces for
        # any future caller that runs migrations against an incomplete DB.
        return

    admin = cursor.execute(
        "SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
    ).fetchone()
    if not admin:
        return
    admin_id = admin[0]

    for table in target_tables:
        cursor.execute(
            f"UPDATE {table} SET owner_id = ? WHERE owner_id IS NULL",
            (admin_id,),
        )

    logger.info("owner_id added to tags/lists/wishlist; legacy rows backfilled to user_id=%d", admin_id)
