# =============================================================================
# Migration 037 — add games.boxart_back (the back of the game's box, PASS-59-225)
# =============================================================================
# Additive. A filename in images/boxart_back/; NULL = no back. Filled by a
# scrape, fill-only like the other pictures, or by an editor's upload.
# Separate from games.box_faces, which only a Slipcase import writes.
# The wishlist table does not get the column.
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists


def apply(conn):
    cursor = conn.cursor()
    if _table_exists(cursor, 'games'):
        _add_column_if_missing(cursor, 'games', 'boxart_back', 'TEXT')
