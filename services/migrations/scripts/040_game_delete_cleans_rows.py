# =============================================================================
# Migration 040 — a deleted game takes its queue and setting rows with it
# =============================================================================
# PASS-59-249. `pending_upscales` (019) and game-scope `emulator_setting_choices`
# rows (018) have no foreign key to games, so a deleted game left them behind,
# and a new game given the same id inherited them. Triggers, as 021 uses, fire
# on every connection whether or not it turned foreign keys on. Rows already
# orphaned are removed.
# =============================================================================

from services.migrations._helpers import _table_exists


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'games'):
        return
    if _table_exists(cursor, 'pending_upscales'):
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_games_delete_pending_upscale
            AFTER DELETE ON games
            BEGIN
                DELETE FROM pending_upscales WHERE game_id = OLD.id;
            END
        """)
        cursor.execute("DELETE FROM pending_upscales WHERE game_id NOT IN (SELECT id FROM games)")
    if _table_exists(cursor, 'emulator_setting_choices'):
        cursor.execute("""
            CREATE TRIGGER IF NOT EXISTS trg_games_delete_setting_choices
            AFTER DELETE ON games
            BEGIN
                DELETE FROM emulator_setting_choices
                WHERE scope = 'game' AND scope_id = OLD.id;
            END
        """)
        cursor.execute("DELETE FROM emulator_setting_choices "
                       "WHERE scope = 'game' AND scope_id NOT IN (SELECT id FROM games)")
