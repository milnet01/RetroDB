# =============================================================================
# Migration 024 — add games.release_dates (release date in each region)
# =============================================================================
# Additive. A JSON object keyed by region code, {"JP": "2002-11-17", ...}; see
# services/release_dates.py. NULL = not known. Filled by the AI during a scrape
# and by AI Fill; nothing is backfilled here.
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists


def apply(conn):
    cursor = conn.cursor()
    if _table_exists(cursor, 'games'):
        _add_column_if_missing(cursor, 'games', 'release_dates', 'TEXT')
