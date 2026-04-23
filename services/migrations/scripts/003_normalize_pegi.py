# =============================================================================
# Migration 003 — promote bare PEGI numbers to "PEGI N" format
# =============================================================================
# Pre-versioned-migrations code shipped a `_migrate_pegi_format` helper that
# ran on every startup. Once user_version reaches 3 this runs once and is
# then skipped forever.
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
    for num in ['3', '7', '12', '16', '18']:
        cursor.execute(
            "UPDATE games SET pegi_rating = ? WHERE pegi_rating = ?",
            (f'PEGI {num}', num),
        )
    logger.info("PEGI format migration completed")
