# =============================================================================
# RETRODB - Database Initialization
# =============================================================================
# Thin wrapper around services.migrations: opens the DB, runs every pending
# migration through the PRAGMA user_version framework, then closes. User
# tables (auth) keep their own bootstrap path because the admin-account
# default-INSERT is a runtime concern, not a schema concern.
# =============================================================================

import logging
import os
import sqlite3

import config
from services.auth import hash_password
from services.migrations import apply_pending, current_version, latest_version

logger = logging.getLogger(__name__)


def _add_column_if_missing(cursor, table, column, coldef):
    """Additive ALTER that no-ops if the column already exists.

    Replaces the `try: ALTER ... except sqlite3.OperationalError: pass`
    idiom — the prior form also swallowed real schema errors (syntax
    typos in `coldef`, missing parent table, locked DB). The explicit
    PRAGMA probe keeps the idempotency while letting surprising errors
    bubble up.
    """
    cols = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
    if column in cols:
        return
    cursor.execute(f"ALTER TABLE {table} ADD COLUMN {column} {coldef}")


def init_database():
    """Run any pending schema/data migrations to bring the DB up to date."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    # Pass 35.1 — DB file carries password hashes and OAuth tokens; tighten
    # the mode to owner-only on every boot (idempotent no-op after the
    # first time). Ignore failures: on Windows / network mounts chmod is a
    # best-effort advisory.
    try:
        if os.path.exists(config.DB_PATH):
            os.chmod(config.DB_PATH, 0o600)
    except OSError:
        pass
    conn = sqlite3.connect(config.DB_PATH)
    try:
        # Pass 35.3 — migration 005 adds REFERENCES users(id) FKs that
        # only runtime get_db() enforces. Turn them on here too so any
        # future FK-sensitive migration step sees consistent enforcement.
        conn.execute("PRAGMA foreign_keys = ON")
        # Pass 35.4 — file-level PRAGMAs applied once per boot, not per
        # connection. Writes to the DB header.
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA journal_size_limit = 67108864")
        # Pass 45.10 — busy_timeout lets BEGIN IMMEDIATE wait up to 5s
        # for the write lock instead of failing fast under contention.
        # Without this, a concurrent reader can make migrations or boot-
        # time bookkeeping flake on multi-worker WSGI deploys.
        conn.execute("PRAGMA busy_timeout = 5000")
        before = current_version(conn)
        applied = apply_pending(conn)
        if applied:
            logger.info(
                "Database migrated %d -> %d (applied %d migration%s)",
                before, latest_version(), len(applied), '' if len(applied) == 1 else 's',
            )
        else:
            logger.info("Database up to date at user_version=%d", latest_version())
        conn.execute("PRAGMA optimize")
        conn.commit()
    finally:
        conn.close()


def ensure_user_tables():
    """Ensure user-related tables exist and seed the default admin account.

    Kept separate from `init_database` because the default-admin INSERT is a
    one-shot bootstrap concern that doesn't fit the append-only schema
    migration model.
    """
    # app.py runs this BEFORE init_database(), so the database/ dir may not
    # exist yet on a fresh install (the bundled PyInstaller standalone has
    # no database/ dir; init_database() creates it but only fires after
    # ensure_user_tables). Hoist the makedirs here too — idempotent.
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    # Pass 45.10 — match the migration runner's busy_timeout so the
    # one-shot users-table bootstrap doesn't fail under WAL contention
    # if a Pass 32.4 health probe happens to fire during boot.
    conn.execute("PRAGMA busy_timeout = 5000")
    # Pass 48.5 — wrap the bootstrap body in try/finally so a mid-way failure
    # (CREATE/ALTER/INSERT flaking under WAL contention) still closes the
    # connection, matching init_database()'s pattern above. Startup aborts on
    # failure either way, but the handle no longer waits on GC to drop the lock.
    try:
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE COLLATE NOCASE,
                display_name TEXT,
                password_hash TEXT,
                role TEXT NOT NULL DEFAULT 'viewer',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                last_login TEXT,
                is_active BOOLEAN DEFAULT 1,
                force_password_change BOOLEAN DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL UNIQUE,
                rpcs3_trophy_path TEXT DEFAULT '',
                ra_username TEXT DEFAULT '',
                ra_api_key TEXT DEFAULT '',
                theme_preference TEXT DEFAULT 'default',
                items_per_page INTEGER DEFAULT 50,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        # Pass 35.5 — additive columns needed for legacy databases that were
        # created before the newer CREATE TABLE shapes shipped. Rolled out of
        # try/except ALTER blocks into an explicit column-existence probe so
        # re-execution is obviously idempotent (no silently-swallowed
        # OperationalError covering unrelated schema bugs). Keep the probe
        # here rather than in a numbered migration because `ensure_user_tables`
        # is the per-boot bootstrap that owns the users/user_settings tables
        # AND has to run before migrations 005-009 see rows to backfill.
        _add_column_if_missing(cursor, 'users', 'force_password_change', 'BOOLEAN DEFAULT 0')
        for _col, _defn in (
            ('avatar', "TEXT DEFAULT ''"),
            ('timezone', "TEXT DEFAULT 'UTC'"),
            # Pass 31.4 — Steam API key + Steam ID per user. Pre-31 these lived
            # in the shared data/scraper_settings.json blob (install-wide) so
            # any logged-in user could launch a sync under the admin's
            # credentials.
            ('psn_username', "TEXT DEFAULT ''"),
            ('psn_npsso', "TEXT DEFAULT ''"),
            ('steam_api_key', "TEXT DEFAULT ''"),
            ('steam_id', "TEXT DEFAULT ''"),
        ):
            _add_column_if_missing(cursor, 'user_settings', _col, _defn)

        cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
        admin_row = cursor.fetchone()

        if not admin_row:
            default_password_hash = hash_password('admin')
            cursor.execute("""
                INSERT INTO users (username, display_name, password_hash, role, force_password_change)
                VALUES (?, ?, ?, ?, ?)
            """, ('admin', 'Administrator', default_password_hash, 'admin', 1))
            admin_id = cursor.lastrowid

            cursor.execute("""
                INSERT INTO user_settings (user_id)
                VALUES (?)
            """, (admin_id,))

            # Pass 41.3.B — log the username only. The bootstrap password is
            # recorded in the README; emitting it to logs created a credential
            # disclosure path that the redactor doesn't catch (its patterns target
            # `password=X` in URLs / `"password": "X"` in JSON, not plaintext).
            logger.info(
                "Created default admin user (username: admin); "
                "set the password on first login or via README bootstrap"
            )
        else:
            admin_id = admin_row['id']

        _backfill_null_owner_ids(cursor, admin_id)

        conn.commit()
    finally:
        conn.close()


def _backfill_null_owner_ids(cursor, admin_id):
    # Idempotent self-heal for installs bitten by the pre-fix migration order
    # bug, where ensure_user_tables() ran AFTER init_database() on an upgrade
    # path that had no users table, causing migrations 005/006 to stamp
    # user_version past their backfill steps without ever seeing an admin row.
    # Runs every startup; WHERE owner_id IS NULL makes it a no-op on healthy DBs.
    targets = (
        ('tags', 'owner_id'),
        ('lists', 'owner_id'),
        ('wishlist', 'owner_id'),
        ('psn_sync_status', 'user_id'),
    )
    for table, column in targets:
        try:
            cols = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
        except sqlite3.OperationalError:
            continue
        if column not in cols:
            continue
        cursor.execute(
            f"UPDATE {table} SET {column} = ? WHERE {column} IS NULL",
            (admin_id,),
        )
        if cursor.rowcount:
            logger.info(
                "Backfilled %d NULL %s row(s) in %s to user_id=%d",
                cursor.rowcount, column, table, admin_id,
            )
