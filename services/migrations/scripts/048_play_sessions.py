# =============================================================================
# Migration 048 — a completion status for each person, and play sessions
# =============================================================================
# PASS-59-332. Additive. user_game_status holds each person's status for a
# game (no row means Not Started); play_sessions holds each Play-button
# session. Every status already set on games.completion_status goes to the
# first admin alone (user, 2026-11-25); the column stays, written by nothing.
# Triggers, as 040 uses, clear both tables when a game or user is deleted on
# a connection that left foreign keys off.
# =============================================================================

from services.migrations._helpers import _admin_user_id, _table_exists


def apply(conn):
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_game_status (
            user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            game_id     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            status      TEXT NOT NULL,
            set_by      TEXT NOT NULL,
            asked       INTEGER NOT NULL DEFAULT 0,
            ask_pending INTEGER NOT NULL DEFAULT 0,
            updated_at  TEXT,
            PRIMARY KEY (user_id, game_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS play_sessions (
            id           INTEGER PRIMARY KEY,
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            game_id      INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            emulator_id  INTEGER,
            started_at   INTEGER NOT NULL,
            seconds      INTEGER NOT NULL,
            save_changed INTEGER NOT NULL DEFAULT 0,
            achievement  INTEGER NOT NULL DEFAULT 0
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_play_sessions_user_game "
                   "ON play_sessions(user_id, game_id)")
    for parent, column in (('games', 'game_id'), ('users', 'user_id')):
        if not _table_exists(cursor, parent):
            continue
        cursor.execute(f"""
            CREATE TRIGGER IF NOT EXISTS trg_{parent}_delete_play_rows
            AFTER DELETE ON {parent}
            BEGIN
                DELETE FROM user_game_status WHERE {column} = OLD.id;
                DELETE FROM play_sessions WHERE {column} = OLD.id;
            END
        """)

    if not _table_exists(cursor, 'games'):
        return
    admin_id = _admin_user_id(cursor)
    if admin_id is None:
        return
    cursor.execute("""
        INSERT OR IGNORE INTO user_game_status (user_id, game_id, status, set_by, updated_at)
        SELECT ?, id, completion_status, 'hand', datetime('now')
        FROM games
        WHERE completion_status IN ('in_progress', 'played', 'completed', '100_percent')
    """, (admin_id,))
