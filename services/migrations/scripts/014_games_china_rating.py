# =============================================================================
# Migration 014 — add games.china_rating (9th rating board: CADPA / China)
# =============================================================================
# Pass 51.2 adds China's CADPA "网络游戏适龄提示" (Online Game Age-Appropriateness
# Reminder) as the 9th age-rating system, mirroring the existing eight. This
# migration just adds the storage column; population happens through the normal
# scrape / AI-fill / manual-edit cross-map path (services.game_utils appends
# 'china' to RATING_SYSTEM_KEYS), so existing rated games pick up a China value
# the next time they are re-scraped or edited — no backfill is forced here.
# =============================================================================

import logging

logger = logging.getLogger(__name__)


def apply(conn):
    cursor = conn.cursor()

    games_exists = cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='games'"
    ).fetchone() is not None
    if not games_exists:
        return

    # Idempotent ADD COLUMN — a legacy install that already carries the column
    # (or a re-run) is a no-op rather than an error.
    cols = {row[1] for row in cursor.execute("PRAGMA table_info(games)")}
    if 'china_rating' not in cols:
        cursor.execute("ALTER TABLE games ADD COLUMN china_rating TEXT")
        logger.info("games.china_rating column added")
