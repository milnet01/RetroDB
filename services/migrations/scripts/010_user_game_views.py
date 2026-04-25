# =============================================================================
# Migration 010 — per-user game-view timestamps (Pass 41.9)
# =============================================================================
# Pre-Pass-41.9, "recently viewed" used the column `games.last_viewed`,
# updated unconditionally by `api_track_view`. On a multi-user install
# that meant whichever user navigated to a game last set the column for
# everyone — admin's game-detail clicks landed in the editor's "recently
# viewed" panel and vice versa. Cross-user leak of viewing history.
#
# This migration creates `user_game_views(user_id, game_id, last_viewed)`
# with a composite PRIMARY KEY (user_id, game_id) so the upsert pattern
# in `api_track_view` is a simple `INSERT INTO ... ON CONFLICT(user_id,
# game_id) DO UPDATE SET last_viewed = excluded.last_viewed`.
#
# We don't drop `games.last_viewed` here — too risky on legacy installs
# that may have other readers we missed. The column becomes vestigial;
# its absence-of-write is the contract going forward.
# =============================================================================

import logging

logger = logging.getLogger(__name__)


def _table_exists(cursor, name):
    return cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def apply(conn):
    cursor = conn.cursor()
    if _table_exists(cursor, 'user_game_views'):
        # Idempotent — re-running is a no-op.
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_user_game_views_user_lastviewed "
            "ON user_game_views(user_id, last_viewed DESC)"
        )
        return

    cursor.execute("""
        CREATE TABLE user_game_views (
            user_id      INTEGER NOT NULL,
            game_id      INTEGER NOT NULL,
            last_viewed  TEXT NOT NULL,
            PRIMARY KEY (user_id, game_id)
        )
    """)
    cursor.execute(
        "CREATE INDEX idx_user_game_views_user_lastviewed "
        "ON user_game_views(user_id, last_viewed DESC)"
    )
    logger.info("user_game_views table created (Pass 41.9)")
