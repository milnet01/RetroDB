# =============================================================================
# Migration helpers — Pass 42.2
# =============================================================================
# Functions previously copy-pasted across migrations 005/006/007/008/009.
# Consolidated here so a fix or hardening lands in one place.
#
# Scope: post-baseline migrations only. Migration 001 keeps its own
# `_add_column_if_missing` because the baseline's lenient try/except predates
# this strict-check pattern and runs against legacy pre-versioned schemas
# whose error surface differs from the cleanly-versioned post-baseline path.
#
# Underscore-prefixed names match the original local helpers so call sites
# in each migration keep reading as `_table_exists(...)` after the import
# swap.
# =============================================================================


def _table_exists(cursor, name):
    return cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _has_column(cursor, table, column):
    cols = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
    return column in cols


def _admin_user_id(cursor):
    """First admin user's id, or None if no users table / no admin row.

    Used by post-baseline backfill migrations to assign legacy single-tenant
    rows to the install's primary admin.
    """
    if not _table_exists(cursor, 'users'):
        return None
    row = cursor.execute(
        "SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _columns_ddl(cols):
    return ',\n    '.join(f"{name} {defn}" for name, defn in cols)


def _add_column_if_missing(cursor, table, column, definition):
    """Strict variant: pre-checks `PRAGMA table_info` rather than swallowing
    `sqlite3.OperationalError`. Catches duplicate-column safely without
    masking unrelated errors (NOT NULL violations, syntax errors, etc.).
    """
    if not _has_column(cursor, table, column):
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
