# =============================================================================
# Migration 022 — the player's name (PASS-59-139)
# =============================================================================
# The player is now the official RetroArch from libretro, downloaded by
# Settings > Emulators > Get RetroArch (user, 2026-10-23). Its row takes that
# name, marked as RetroDB's copy so it is told apart from the user's own
# RetroArch row. Renames only migration 020's placeholder, so a name the user
# chose is kept.
# =============================================================================

from services.migrations._helpers import _table_exists

OLD_NAME = 'RetroDB Player'
PLAYER_NAME = 'RetroArch (RetroDB)'


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'emulators'):
        return
    cursor.execute("""
        UPDATE emulators
        SET name = ?, description = 'Official RetroArch, set up by RetroDB',
            updated_at = datetime('now')
        WHERE is_player = 1 AND name = ?
          AND NOT EXISTS (SELECT 1 FROM emulators WHERE name = ?)
    """, (PLAYER_NAME, OLD_NAME, PLAYER_NAME))
