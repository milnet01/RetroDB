# =============================================================================
# Migration 032 — whether this copy can earn RetroAchievements
# =============================================================================
# PASS-59-217. 1: RetroAchievements lists this file's hash. 0: it lists others
# and not this one. NULL: RetroDB cannot tell. Filled by the next link check.
# =============================================================================

from services.migrations._helpers import _has_column


def apply(conn):
    c = conn.cursor()
    if not _has_column(c, 'games', 'ra_copy_fits'):
        c.execute("ALTER TABLE games ADD COLUMN ra_copy_fits INTEGER")
