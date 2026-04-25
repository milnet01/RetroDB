# =============================================================================
# Migration 010 — multi-emulator launch (Pass 42)
# =============================================================================
# Adds the emulator registry (`emulators`) and per-system mapping
# (`system_emulators`) tables, plus two override columns on `games`. Mirrors
# the `controllers` / `system_controllers` shape established in baseline.
#
# Idempotent: re-applying produces no diff. Existing rows are not touched.
# Seed data is loaded from data/emulator_seeds.json on Flask startup (see
# app.py); this migration only creates schema.
# =============================================================================

import logging
import sqlite3

logger = logging.getLogger(__name__)


def _add_column_if_missing(c, table, col_name, col_type):
    try:
        c.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
    except sqlite3.OperationalError:
        pass


def apply(conn):
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS emulators (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            name                  TEXT NOT NULL UNIQUE,
            binary_name           TEXT NOT NULL,
            binary_path_override  TEXT,
            args_template         TEXT NOT NULL,
            is_retroarch          INTEGER NOT NULL DEFAULT 0,
            description           TEXT,
            enabled               INTEGER NOT NULL DEFAULT 1,
            created_at            TEXT,
            updated_at            TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS system_emulators (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id       INTEGER NOT NULL REFERENCES systems(id) ON DELETE CASCADE,
            emulator_id     INTEGER NOT NULL REFERENCES emulators(id) ON DELETE CASCADE,
            is_default      INTEGER NOT NULL DEFAULT 0,
            retroarch_core  TEXT,
            extra_args      TEXT,
            UNIQUE(system_id, emulator_id)
        )
    """)

    _add_column_if_missing(c, 'games', 'emulator_override_id', 'INTEGER REFERENCES emulators(id)')
    _add_column_if_missing(c, 'games', 'launch_args_override', 'TEXT')

    c.execute("CREATE INDEX IF NOT EXISTS idx_system_emulators_system  ON system_emulators(system_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_system_emulators_default ON system_emulators(system_id, is_default)")

    conn.commit()
    logger.info("migration 010 applied: emulators + system_emulators + games override columns")
