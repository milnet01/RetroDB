# =============================================================================
# Migration 046 — MobyGames: its id, its score, box scans, the catch-up list
# =============================================================================
# PASS-59-183. Additive. games.mobygames_id and games.moby_score are filled
# fill-only by a scrape. games.box_scans holds the JSON record of one real
# release's scans (services/box_scans.py); NULL = none. mobygames_pending lists
# games a scrape passed over because the hour's allowance was spent, for
# services/jobs/mobygames_catch_up.py. A trigger, as 040 uses, empties a
# deleted game's row on connections that leave foreign keys off.
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'games'):
        return
    _add_column_if_missing(cursor, 'games', 'mobygames_id', 'INTEGER')
    _add_column_if_missing(cursor, 'games', 'moby_score', 'REAL')
    _add_column_if_missing(cursor, 'games', 'box_scans', 'TEXT')
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS mobygames_pending (
            game_id INTEGER PRIMARY KEY REFERENCES games(id) ON DELETE CASCADE,
            added_at TEXT
        )
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_games_delete_mobygames_pending
        AFTER DELETE ON games
        BEGIN
            DELETE FROM mobygames_pending WHERE game_id = OLD.id;
        END
    """)
