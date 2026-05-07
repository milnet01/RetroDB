# =============================================================================
# Migration 011 — CASCADE FKs on user_game_views (Pass 45.15)
# =============================================================================
# Migration 010 created user_game_views with a composite PRIMARY KEY but
# no FOREIGN KEY clauses. When a game or user was deleted, rows in
# user_game_views were left orphaned — the recently-viewed dropdown ran a
# JOIN against `games` and silently skipped the orphaned rows, but they
# accumulated forever in the table. On a long-lived install with regular
# game-deletes from the rom-tools pipelines (chd_converter, duplicate_finder
# delete-and-replace flow), the table could grow to tens of thousands of
# dead rows pointing nowhere.
#
# Fix: rebuild the table with `FOREIGN KEY (game_id) REFERENCES games(id)
# ON DELETE CASCADE` and `FOREIGN KEY (user_id) REFERENCES users(id) ON
# DELETE CASCADE`. SQLite can't add FK constraints to an existing table
# without rebuilding it (PRAGMA foreign_keys won't enforce a constraint
# that wasn't in the CREATE TABLE statement), so this follows the canonical
# 12-step rebuild + scoped foreign_key_check (Pass 45.10 pattern).
#
# Backfill: rows referencing now-deleted games/users are dropped during
# the INSERT (LEFT JOIN games/users ON ... WHERE games.id IS NULL → skip).
# This is the equivalent of running ON DELETE CASCADE retroactively.
#
# Why a rebuild even on installs with no orphans: the absence of the FK
# constraint is itself the bug — if you don't add it now, the next
# orphan-creating event will repeat the cycle. Idempotent: skip if the FK
# is already present.
# =============================================================================

import logging

logger = logging.getLogger(__name__)


def _table_exists(cursor, name):
    return cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _foreign_key_count(cursor, table):
    """Return the number of FK clauses defined on `table`."""
    return len(cursor.execute(f"PRAGMA foreign_key_list({table})").fetchall())


def apply(conn):
    cursor = conn.cursor()

    if not _table_exists(cursor, 'user_game_views'):
        # Migration 010 didn't run on this DB; nothing to upgrade.
        return

    # Idempotent: if the table already has 2 FK clauses (game_id + user_id),
    # we've already rebuilt it. Skip.
    if _foreign_key_count(cursor, 'user_game_views') >= 2:
        return

    # `defer_foreign_keys = ON` is the in-transaction equivalent of
    # disabling FK enforcement; it auto-resets at COMMIT.
    cursor.execute("PRAGMA defer_foreign_keys = ON")

    cursor.execute("""
        CREATE TABLE user_game_views_new (
            user_id      INTEGER NOT NULL,
            game_id      INTEGER NOT NULL,
            last_viewed  TEXT NOT NULL,
            PRIMARY KEY (user_id, game_id),
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
    """)

    pre_count = cursor.execute(
        "SELECT COUNT(*) FROM user_game_views"
    ).fetchone()[0]
    pruned = 0
    # Only attempt the orphan-pruning INSERT if both parent tables exist.
    # Minimal-schema test fixtures may run migrations against a DB that
    # doesn't have games/users; on those, an empty source table means
    # nothing to migrate. Production always has both tables (baseline +
    # migration 005), so this guard is purely a test-fixture courtesy.
    if pre_count > 0 and _table_exists(cursor, 'games') and _table_exists(cursor, 'users'):
        cursor.execute("""
            INSERT INTO user_game_views_new (user_id, game_id, last_viewed)
            SELECT v.user_id, v.game_id, v.last_viewed
            FROM user_game_views v
            INNER JOIN games g ON g.id = v.game_id
            INNER JOIN users u ON u.id = v.user_id
        """)
        post_count = cursor.execute(
            "SELECT COUNT(*) FROM user_game_views_new"
        ).fetchone()[0]
        pruned = pre_count - post_count

    cursor.execute("DROP TABLE user_game_views")
    cursor.execute("ALTER TABLE user_game_views_new RENAME TO user_game_views")
    cursor.execute(
        "CREATE INDEX idx_user_game_views_user_lastviewed "
        "ON user_game_views(user_id, last_viewed DESC)"
    )

    # Pass 45.10 — scoped FK check on the rebuilt table only. The unscoped
    # form catches every FK in the DB, which is too aggressive on legacy
    # installs that may have unrelated dangling refs.
    violations = cursor.execute(
        "PRAGMA foreign_key_check(user_game_views)"
    ).fetchall()
    if violations:
        raise RuntimeError(
            f"Migration 011 left foreign-key violations on user_game_views: "
            f"{violations}"
        )

    logger.info(
        "user_game_views rebuilt with CASCADE FKs (pruned %d orphan rows)",
        pruned,
    )
