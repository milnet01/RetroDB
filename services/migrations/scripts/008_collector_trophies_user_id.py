# =============================================================================
# Migration 008 — user_id on collector_trophies (Pass 31.3)
# =============================================================================
# Pre-Pass-31, `collector_trophies` keyed on `id TEXT PRIMARY KEY` — one row
# per trophy definition, shared across every logged-in user. That meant:
#   * whichever user hit "refresh" last overwrote the earned_at / progress
#     fields everyone else saw,
#   * user B's Collector Rank badge in the sidebar was whatever user A had
#     most recently unlocked,
#   * the rank threshold was computed against a stat mix that aggregated
#     every user's achievements + wishlist + PSN progress together.
#
# This migration rebuilds the table with a composite PRIMARY KEY on
# (id, user_id), backfills every pre-existing row to the first admin user
# (matching the single-tenant pre-Pass-27 assumption), and adds a user_id
# index for the per-user reads.
#
# Why a rebuild: the old primary key is `id TEXT PRIMARY KEY` — SQLite can't
# ALTER a primary key, only recreate the table around it. Steps follow the
# canonical 12-step procedure.
# =============================================================================

import logging

from services.migrations._helpers import (
    _admin_user_id,
    _columns_ddl,
    _has_column,
    _table_exists,
)

logger = logging.getLogger(__name__)


_COLUMNS = [
    ('id', 'TEXT NOT NULL'),
    ('user_id', 'INTEGER NOT NULL'),
    ('name', 'TEXT NOT NULL'),
    ('description', 'TEXT'),
    ('icon', 'TEXT NOT NULL'),
    ('tier', "TEXT NOT NULL DEFAULT 'bronze'"),
    ('category', "TEXT NOT NULL DEFAULT 'general'"),
    ('threshold', 'INTEGER DEFAULT 0'),
    ('earned_at', 'TEXT'),
    ('progress', 'INTEGER DEFAULT 0'),
]


def apply(conn):
    cursor = conn.cursor()
    # `PRAGMA foreign_keys = OFF` is a no-op inside a transaction; use
    # `defer_foreign_keys = ON` instead (auto-resets at COMMIT).
    cursor.execute("PRAGMA defer_foreign_keys = ON")

    if not _table_exists(cursor, 'collector_trophies'):
        # Baseline always creates this table, so hitting this branch means
        # the caller is running migrations against an incomplete DB. Let
        # baseline own the creation; this migration only reshapes.
        return

    if _has_column(cursor, 'collector_trophies', 'user_id'):
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_collector_trophies_user "
            "ON collector_trophies(user_id)"
        )
        return

    admin_id = _admin_user_id(cursor)
    if admin_id is None:
        # No admin user to backfill to — seed an empty reshape and let the
        # next /api/collector-trophies/refresh populate the table. Without
        # data there's nothing to lose in the rebuild.
        existing_rows = 0
    else:
        row = cursor.execute("SELECT COUNT(*) FROM collector_trophies").fetchone()
        existing_rows = row[0] if row else 0

    # Preserve column ordering with the new user_id column immediately after id
    # so existing DELETE-by-id patterns still read naturally.
    cursor.execute(f"""
        CREATE TABLE collector_trophies_new (
            {_columns_ddl(_COLUMNS)},
            PRIMARY KEY (id, user_id)
        )
    """)

    if existing_rows and admin_id is not None:
        cursor.execute(
            "INSERT INTO collector_trophies_new "
            "(id, user_id, name, description, icon, tier, category, threshold, earned_at, progress) "
            "SELECT id, ?, name, description, icon, tier, category, threshold, earned_at, progress "
            "FROM collector_trophies",
            (admin_id,),
        )

    cursor.execute("DROP TABLE collector_trophies")
    cursor.execute("ALTER TABLE collector_trophies_new RENAME TO collector_trophies")
    cursor.execute(
        "CREATE INDEX idx_collector_trophies_user ON collector_trophies(user_id)"
    )
    cursor.execute(
        "CREATE INDEX idx_collector_trophies_tier ON collector_trophies(tier)"
    )

    # defer_foreign_keys auto-resets at COMMIT — no explicit restoration needed.

    # Pass 45.10 — scope FK check to the rebuilt table so pre-existing
    # data-integrity issues elsewhere don't block the migration.
    violations = cursor.execute(
        "PRAGMA foreign_key_check(collector_trophies)"
    ).fetchall()
    if violations:
        raise RuntimeError(
            f"Migration 008 left foreign-key violations on collector_trophies: "
            f"{violations}"
        )

    logger.info(
        "collector_trophies rebuilt with (id, user_id) composite PK "
        "(backfilled %d rows to admin_id=%s)",
        existing_rows, admin_id,
    )
