# =============================================================================
# Migration 028 — clear the save types guessed per cartridge system
# =============================================================================
# PASS-59-211. Scrapes wrote these two wordings for every game on a cartridge
# system that reached that step, though many of those games save nothing. No
# other source and no form writes them, so each row holds a guess, not a fact.
# =============================================================================

from services.migrations._helpers import _table_exists


def apply(conn):
    cursor = conn.cursor()
    if _table_exists(cursor, 'games'):
        cursor.execute("UPDATE games SET save_type = NULL "
                       "WHERE save_type IN ('Battery Save / SRAM', 'Password / None')")
