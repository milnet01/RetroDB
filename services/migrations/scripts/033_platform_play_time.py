# =============================================================================
# Migration 033 — play time a service reports, per user
# =============================================================================
# PASS-59-218. Steam says how long each person played and when they last did.
# It belongs to the person, not the game, so it is not a `games` column.
# =============================================================================


def apply(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS platform_play_time (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            source TEXT NOT NULL,
            minutes INTEGER NOT NULL DEFAULT 0,
            last_played INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT,
            PRIMARY KEY (user_id, game_id, source)
        )
    """)
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_platform_play_time_game ON platform_play_time(game_id)")
