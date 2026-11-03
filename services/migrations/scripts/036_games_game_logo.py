# =============================================================================
# Migration 036 — add games.game_logo (the game's logo picture, PASS-59-224)
# =============================================================================
# Additive. A filename in images/game_logos/; NULL = no logo. Filled by a
# scrape, fill-only like the other pictures, or by an editor's upload.
# The wishlist table does not get the column.
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists


def apply(conn):
    cursor = conn.cursor()
    if _table_exists(cursor, 'games'):
        _add_column_if_missing(cursor, 'games', 'game_logo', 'TEXT')
