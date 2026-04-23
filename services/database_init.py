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


def init_database():
    """Run any pending schema/data migrations to bring the DB up to date."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    try:
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
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
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

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN force_password_change BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass

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

    try:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN avatar TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN timezone TEXT DEFAULT 'UTC'")
    except sqlite3.OperationalError:
        pass

    cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    admin_exists = cursor.fetchone()

    if not admin_exists:
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

        logger.info("Created default admin user (username: admin, password: admin)")

    conn.commit()
    conn.close()
