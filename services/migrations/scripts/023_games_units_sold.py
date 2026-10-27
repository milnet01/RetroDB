# =============================================================================
# Migration 023 — add games.units_sold (lifetime sales, filled by the AI)
# =============================================================================
# Additive. The number of copies a game sold worldwide on the platform of its
# row, as an integer. NULL = not known. Filled by the AI during a scrape and by
# AI Fill; no other scraper supplies it, so nothing is backfilled here.
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists


def apply(conn):
    cursor = conn.cursor()
    if _table_exists(cursor, 'games'):
        _add_column_if_missing(cursor, 'games', 'units_sold', 'INTEGER')
