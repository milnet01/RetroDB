# =============================================================================
# Migration 049 — add games.sales_all_platforms (a sales total across consoles)
# =============================================================================
# PASS-59-343. Additive. A published lifetime sales total that covers several
# platforms, as JSON {"units": int, "platforms": "PS4, Xbox One, PC"}. NULL =
# not known. Filled by the AI alongside units_sold; shown on the analytics page
# only, because it is not the row's own console's figure (user, 2026-11-25).
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists


def apply(conn):
    cursor = conn.cursor()
    if _table_exists(cursor, 'games'):
        _add_column_if_missing(cursor, 'games', 'sales_all_platforms', 'TEXT')
