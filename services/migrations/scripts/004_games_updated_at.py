# =============================================================================
# Migration 004 — add games.updated_at + auto-refresh triggers
# =============================================================================
# Pass 21 (request-level caching & ETags) keys the cache hash off
# MAX(games.updated_at). For that to work every INSERT/UPDATE path must leave
# the column fresh without each callsite having to remember — so this
# migration adds the column, backfills it (preferring created_at where we
# have it), and installs two SQLite triggers that set/refresh updated_at
# automatically.
#
# SQLite's default is `recursive_triggers = OFF`, so the UPDATE trigger's
# inner UPDATE does not re-fire itself. If a future PRAGMA change flips
# recursion on, the WHEN clause still short-circuits on the second pass
# (the column is already the same value).
# =============================================================================

import logging

logger = logging.getLogger(__name__)


def apply(conn):
    cursor = conn.cursor()

    games_exists = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='games'"
    ).fetchone() is not None
    if not games_exists:
        return

    # ALTER TABLE ADD COLUMN — idempotent via PRAGMA table_info lookup so
    # legacy installs that already carry the column (if any hand-patched one
    # exists) don't error out.
    cols = {row[1] for row in cursor.execute("PRAGMA table_info(games)")}
    if 'updated_at' not in cols:
        cursor.execute("ALTER TABLE games ADD COLUMN updated_at TEXT")

    # Backfill: prefer existing created_at where present; otherwise stamp
    # with the migration timestamp so MAX(updated_at) on a fresh-post-migration
    # query is well-defined. Only rows with NULL updated_at are touched so
    # re-running the migration is a no-op.
    cursor.execute(
        "UPDATE games "
        "SET updated_at = COALESCE(created_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')) "
        "WHERE updated_at IS NULL"
    )

    # Index: MAX(updated_at) scans are frequent (one per card-data request)
    # and a btree makes them O(log n) instead of a full table scan.
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_games_updated_at ON games(updated_at)"
    )

    # INSERT trigger: stamp on brand-new rows when the caller did not supply
    # a value. Rows created during the backfill above already have a value
    # so the trigger is a no-op on them.
    cursor.execute(
        "CREATE TRIGGER IF NOT EXISTS games_updated_at_on_insert "
        "AFTER INSERT ON games "
        "FOR EACH ROW WHEN NEW.updated_at IS NULL "
        "BEGIN "
        "  UPDATE games SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "  WHERE id = NEW.id; "
        "END"
    )

    # UPDATE trigger: refresh on every row modification. The WHEN clause
    # prevents the trigger from firing on its own inner UPDATE — both with
    # and without recursive_triggers enabled.
    cursor.execute(
        "CREATE TRIGGER IF NOT EXISTS games_updated_at_on_update "
        "AFTER UPDATE ON games "
        "FOR EACH ROW WHEN NEW.updated_at IS OLD.updated_at "
        "BEGIN "
        "  UPDATE games SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') "
        "  WHERE id = NEW.id; "
        "END"
    )

    logger.info("games.updated_at column + triggers installed")
