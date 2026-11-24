# =============================================================================
# Migration 047 — the case a person picked for a game's built 3D box
# =============================================================================
# PASS-59-329. Additive. games.box_case names a case in
# services/box3d/cases.py::CASE_TYPES that a built box is drawn on; NULL lets
# services/box3d/build.py::case_for_game choose.
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'games'):
        return
    _add_column_if_missing(cursor, 'games', 'box_case', 'TEXT')
