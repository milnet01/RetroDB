# =============================================================================
# Migration 025 — add games.box_faces (a Slipcase box's faces, PASS-59-142)
# =============================================================================
# Additive. A JSON record of the case, its colours and the face files in
# images/box_faces/; see services/box_faces.py. NULL = no faces imported.
# Filled only by an editor's import on the game page; nothing is backfilled.
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists


def apply(conn):
    cursor = conn.cursor()
    if _table_exists(cursor, 'games'):
        _add_column_if_missing(cursor, 'games', 'box_faces', 'TEXT')
