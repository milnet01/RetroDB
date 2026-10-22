# =============================================================================
# Migration 020 — the bundled player's emulator row (PASS-59-64 §4.4)
# =============================================================================
# Additive: `emulators.is_player` marks the row the resolver's player branch
# serves, and the player's row itself, with no `system_emulators` rows. The
# core installer (PASS-59-81) maps it to a system when it installs a core.
# `args_template` is NOT NULL but unused: the player's argv is built by the
# resolver, not from a template. The name is a placeholder (PASS-59-64 §3, item 10).
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists

PLAYER_NAME = 'RetroDB Player'


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'emulators'):
        return
    _add_column_if_missing(cursor, 'emulators', 'is_player',
                           'INTEGER NOT NULL DEFAULT 0')
    cursor.execute("""
        INSERT OR IGNORE INTO emulators
            (name, binary_name, args_template, is_retroarch, is_player,
             description, enabled, created_at, updated_at)
        VALUES (?, 'retrodb-player', '-L "{retroarch_core}" "{rom}"', 0, 1,
                'Based on RetroArch', 1, datetime('now'), datetime('now'))
    """, (PLAYER_NAME,))
