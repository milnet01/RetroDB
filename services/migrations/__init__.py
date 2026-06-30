# =============================================================================
# RETRODB - Schema migrations
# =============================================================================
# Versioned schema/data migrations driven by SQLite's `PRAGMA user_version`.
#
# Each migration lives in `services/migrations/scripts/NNN_description.py` and
# exposes a single `apply(conn)` callable. The ordered MIGRATIONS list below
# maps version numbers (1-indexed, in declaration order) to those modules;
# `apply_pending(conn)` runs every migration whose version exceeds the DB's
# current `user_version` and bumps `user_version` to match after each step.
#
# Authoring rules — see docs/RETRODB_DESIGN_STANDARDS.md §25:
#   * Migrations are append-only once shipped.
#   * Filename: `NNN_description.py` (NNN is zero-padded, matches list order).
#   * `apply(conn)` must be idempotent (so legacy installs that already carry
#     the change can run it as a no-op without error).
# =============================================================================

import importlib
import logging

logger = logging.getLogger(__name__)

# Ordered migration list. Append new entries; never reorder or delete a shipped
# entry. The 1-indexed position in this list IS the user_version it advances
# the database to after running.
MIGRATIONS = [
    '001_baseline',
    '002_normalize_genres',
    '003_normalize_pegi',
    '004_games_updated_at',
    '005_collections_owner_id',
    '006_per_user_platform_tokens',
    '007_psn_user_id',
    '008_collector_trophies_user_id',
    '009_achievement_tables_user_id',
    '010_user_game_views',
    '011_user_game_views_cascade_fk',
    '012_emulators',
    '013_fresh_install_schema_backfill',
]


def _load(name):
    return importlib.import_module(f'services.migrations.scripts.{name}')


def current_version(conn):
    """Return the DB's current schema version (PRAGMA user_version)."""
    return conn.execute("PRAGMA user_version").fetchone()[0]


def latest_version():
    """Return the highest version number defined in MIGRATIONS."""
    return len(MIGRATIONS)


def apply_pending(conn):
    """Run every migration whose version exceeds the DB's current user_version.

    Each migration runs in its own transaction; user_version is advanced inside
    the same transaction so a crash mid-migration cannot leave the DB in a
    half-applied state with the version already bumped.

    Args:
        conn: Open sqlite3.Connection.

    Returns:
        list[int]: Versions applied this call (empty if already up-to-date).
    """
    applied = []
    current = current_version(conn)
    target = latest_version()
    if current > target:
        # DB is newer than the code — likely a downgrade. Refuse rather than
        # try to "fix" it.
        raise RuntimeError(
            f"Database user_version ({current}) is newer than the latest "
            f"migration this build knows about ({target}). Refusing to run."
        )
    for idx, name in enumerate(MIGRATIONS):
        version = idx + 1
        if version <= current:
            continue
        module = _load(name)
        try:
            # Pass 45.10 — BEGIN IMMEDIATE acquires the write lock up
            # front instead of waiting for the first write. Plain BEGIN
            # (= BEGIN DEFERRED) lets concurrent readers sneak in between
            # the BEGIN and the first DDL, and table-rebuild migrations
            # (007/008/009) can deadlock under WAL when a long-running
            # reader holds the write-blocking shared lock. With
            # busy_timeout already set on the connection, IMMEDIATE will
            # wait politely rather than fail-fast on contention.
            conn.execute("BEGIN IMMEDIATE")
            module.apply(conn)
            conn.execute(f"PRAGMA user_version = {version}")
            conn.commit()
        except Exception:
            conn.rollback()
            logger.exception("Migration %s (v%d) failed; rolled back", name, version)
            raise
        applied.append(version)
        logger.info("Applied migration %s (user_version -> %d)", name, version)
    return applied
