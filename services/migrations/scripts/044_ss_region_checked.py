# =============================================================================
# Migration 044 — remember a game the region fix has settled (PASS-59-202)
# =============================================================================
# The box and manual region fix asks ScreenScraper about every game holding a
# file an older scrape chose. ss_region_checked = 1 records that each such file
# is right, so no later run asks about the game again.
# =============================================================================

from services.migrations._helpers import _has_column


def apply(conn):
    c = conn.cursor()
    if not _has_column(c, 'games', 'ss_region_checked'):
        c.execute("ALTER TABLE games ADD COLUMN ss_region_checked INTEGER NOT NULL DEFAULT 0")
