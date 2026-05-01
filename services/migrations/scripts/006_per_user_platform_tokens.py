# =============================================================================
# Migration 006 — per-user PSN / Xbox tokens (Pass 27.2)
# =============================================================================
# Pre-Pass-27, PSN OAuth tokens lived in `data/psn_tokens.json` and Xbox
# OAuth tokens in `data/xbox_tokens.json` — one file per install, no concept
# of "whose tokens". On a multi-user install that meant whichever user happened
# to authenticate first leaked their account to every other logged-in user
# (their PSN avatar, online_id, and trophy library all rendered for everyone).
#
# This migration creates `user_platform_tokens(user_id, platform, tokens, …)`
# and ingests the legacy single-tenant token files into the row keyed by the
# first admin's id, then deletes the files so subsequent saves only ever touch
# the table.
#
# `psn_sync_status` historically used `WHERE id = 1` as the singleton key. We
# add `user_id` (NOT NULL after backfill), a UNIQUE constraint on it so the
# existing INSERT-OR-REPLACE pattern can pivot from id to user_id, and an
# index. Routes scope status reads by `g.user['id']`; the sync writer now
# upserts under that key.
# =============================================================================

import json
import logging
import os

from services.migrations._helpers import _add_column_if_missing, _table_exists

logger = logging.getLogger(__name__)


def _data_dir(cursor):
    """Best-effort path to the data/ directory for ingesting legacy token files.

    The migration runs against an open sqlite3 connection — the file's path is
    accessible via `PRAGMA database_list`, and the legacy token files have
    always lived as siblings of the DB file (they share the data/ folder).
    """
    row = cursor.execute("PRAGMA database_list").fetchone()
    if not row:
        return None
    db_path = row[2]
    if not db_path:
        return None
    return os.path.dirname(os.path.abspath(db_path))


def apply(conn):
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_platform_tokens (
            user_id INTEGER NOT NULL,
            platform TEXT NOT NULL,
            tokens TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            PRIMARY KEY (user_id, platform),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    # If a users table exists, locate the first admin so we can ingest legacy
    # data under their id. A missing users table means the caller is running
    # migrations before ensure_user_tables() has bootstrapped the admin — the
    # normal init path (see services/database_init.py, post-Pass-30.1) seeds
    # users first so we rarely hit this branch, but keep it as a defensive
    # no-op since there's nothing to ingest without an admin id.
    if not _table_exists(cursor, 'users'):
        return

    admin = cursor.execute(
        "SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
    ).fetchone()
    admin_id = admin[0] if admin else None

    # Ingest legacy token JSON files into the table for the first admin.
    # Best-effort: any file-system or JSON error leaves the file in place so
    # the next admin sync re-creates the row from a fresh OAuth flow.
    data_dir = _data_dir(cursor)
    if data_dir and admin_id is not None:
        for filename, platform in (('psn_tokens.json', 'psn'), ('xbox_tokens.json', 'xbox')):
            path = os.path.join(data_dir, filename)
            if not os.path.exists(path):
                continue
            try:
                with open(path, 'r') as f:
                    raw = f.read()
                # Validate JSON structure but store the original text — the
                # caller reads `tokens` back through json.loads, so identical
                # round-trip behaviour preserves any vendor-specific fields.
                json.loads(raw)
                cursor.execute(
                    "INSERT OR REPLACE INTO user_platform_tokens (user_id, platform, tokens) "
                    "VALUES (?, ?, ?)",
                    (admin_id, platform, raw),
                )
                # Successfully migrated — remove the file. Best-effort; if the
                # remove fails (read-only fs, permission), the table version
                # still wins because the loader checks the table first.
                try:
                    os.remove(path)
                    logger.info("Ingested %s into user_platform_tokens (user=%d), removed file", filename, admin_id)
                except OSError as e:
                    logger.warning("Ingested %s into user_platform_tokens but could not remove file: %s", filename, e)
            except (OSError, ValueError) as e:
                logger.warning("Could not ingest %s into user_platform_tokens: %s", filename, e)

    # psn_sync_status: add user_id column + UNIQUE index so the singleton-ish
    # INSERT-OR-REPLACE pattern can pivot from `id=1` to `user_id=?`.
    if _table_exists(cursor, 'psn_sync_status'):
        _add_column_if_missing(cursor, 'psn_sync_status', 'user_id', 'INTEGER REFERENCES users(id)')
        if admin_id is not None:
            cursor.execute(
                "UPDATE psn_sync_status SET user_id = ? WHERE user_id IS NULL",
                (admin_id,),
            )
        # UNIQUE index — must be created with WHERE user_id IS NOT NULL
        # because legacy NULL rows can't both backfill and stay UNIQUE if
        # admin lookup ever fails.
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_psn_sync_status_user_id "
            "ON psn_sync_status(user_id) WHERE user_id IS NOT NULL"
        )
