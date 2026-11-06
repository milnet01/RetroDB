# =============================================================================
# Migration 041 — a PSN game link says whether a person set it
# =============================================================================
# PASS-59-260. The PSN sync kept every stored link, because a link set by hand
# looked like one the sync made. So a wrong automatic link from the old loose
# matcher ("Pac-Man World Re-Pac" to a PS1 game named "D") never changed.
# `link_set_by_hand` = 1 is never changed by a sync. Older links are taken as
# automatic, so the next sync checks them again (user, 2026-11-06), except the
# link to the game the PSN import made for that title.
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'psn_games'):
        return
    _add_column_if_missing(cursor, 'psn_games', 'link_set_by_hand', 'INTEGER NOT NULL DEFAULT 0')
    cursor.execute("""
        UPDATE psn_games SET link_set_by_hand = 1
        WHERE linked_game_id IN (
            SELECT id FROM games
            WHERE rom_path LIKE 'psn_import/%/' || psn_games.npwr_id)
    """)
