# =============================================================================
# Migration 018 — per-game settings for standalone emulators (PASS-59-91 §4.6)
# =============================================================================
# Additive:
#   * `games.disc_serial` / `games.disc_crc` — the disc ids DuckStation, PCSX2
#     and RPCS3 name their per-game files by. NULL = not read yet; '' = read,
#     none found. A changed `rom_path` clears both (trigger), so they re-read.
#   * `emulator_setting_choices` — the user's per-system and per-game choices.
#   * `emulator_written_settings` — the raw value RetroDB last wrote to each
#     managed key of each file, which tells RetroDB's keys from the user's.
# Also moves the seeded DuckStation and PCSX2 `args_template` onto
# `{fullscreen_flag}`, only where it still equals the old seed exactly.
# =============================================================================

import logging

from services.migrations._helpers import _add_column_if_missing, _table_exists

logger = logging.getLogger(__name__)

_OLD_SEED = '-batch -fullscreen "{rom}"'
_NEW_SEED = '-batch {fullscreen_flag} "{rom}"'


def apply(conn):
    cursor = conn.cursor()
    if _table_exists(cursor, 'games'):
        _add_column_if_missing(cursor, 'games', 'disc_serial', 'TEXT')
        _add_column_if_missing(cursor, 'games', 'disc_crc', 'TEXT')
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_games_rom_path_clears_disc_ids
            AFTER UPDATE OF rom_path ON games
            WHEN NEW.rom_path IS NOT OLD.rom_path
            BEGIN
                UPDATE games SET disc_serial = NULL, disc_crc = NULL WHERE id = NEW.id;
            END
        """)
    if not _table_exists(cursor, 'emulators'):
        return
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emulator_setting_choices (
            id          INTEGER PRIMARY KEY,
            emulator_id INTEGER NOT NULL REFERENCES emulators(id) ON DELETE CASCADE,
            scope       TEXT NOT NULL CHECK (scope IN ('system', 'game')),
            scope_id    INTEGER NOT NULL,
            setting     TEXT NOT NULL,
            value       TEXT NOT NULL,
            UNIQUE (emulator_id, scope, scope_id, setting)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emulator_written_settings (
            id          INTEGER PRIMARY KEY,
            emulator_id INTEGER NOT NULL REFERENCES emulators(id) ON DELETE CASCADE,
            file_path   TEXT NOT NULL,
            setting     TEXT NOT NULL,
            written     TEXT NOT NULL,
            UNIQUE (file_path, setting)
        )
    """)
    cursor.execute("""
        UPDATE emulators SET args_template = ?
        WHERE binary_name IN ('duckstation-qt', 'pcsx2-qt') AND args_template = ?
    """, (_NEW_SEED, _OLD_SEED))
    logger.info("standalone emulator settings schema added")
