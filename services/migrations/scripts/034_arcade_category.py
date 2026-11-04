# =============================================================================
# Migration 034 — an arcade set's category (PASS-59-227)
# =============================================================================
# Lets the MAME list be filtered by kind of machine. `BIOS` hides a row from
# game lists; its file stays on disk because other sets need it.
# =============================================================================

from services.migrations._helpers import _has_column


def apply(conn):
    c = conn.cursor()
    if not _has_column(c, 'games', 'arcade_category'):
        c.execute("ALTER TABLE games ADD COLUMN arcade_category TEXT")
