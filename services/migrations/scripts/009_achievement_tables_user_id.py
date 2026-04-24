# =============================================================================
# Migration 009 — user_id on achievement tables (Pass 31.2)
# =============================================================================
# Three tables — `game_achievement_progress`, `steam_achievements`, and
# `xbox_achievements` — were keyed on `(game_id, apiname)` / `(game_id,
# achievement_id)` / `game_id UNIQUE` alone. In a multi-user install user B's
# Steam/Xbox/RA sync overwrote user A's completion percentage; a global
# DELETE in `/api/refresh-retroachievements` wiped everyone's RA progress in
# one go.
#
# This migration:
#   - adds `user_id INTEGER NOT NULL REFERENCES users(id)` to all three
#     tables (rebuild for game_achievement_progress whose `game_id UNIQUE`
#     inline constraint prevents per-user rows; ALTER + composite UNIQUE for
#     the other two),
#   - backfills every existing row to the first admin user,
#   - replaces the old UNIQUE keys with composite keys that include user_id.
#
# Callers must pass `user_id` on every upsert and scope every SELECT; see
# routes/ra_sync.py, routes/steam_achievements.py, routes/xbox_achievements.py,
# routes/achievements.py, and services/jobs/platform_sync.py for the
# per-site changes.
# =============================================================================

import logging

logger = logging.getLogger(__name__)


_GAP_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('game_id', 'INTEGER NOT NULL'),
    ('user_id', 'INTEGER NOT NULL'),
    ('ra_game_id', 'INTEGER'),
    ('earned_achievements', 'INTEGER DEFAULT 0'),
    ('total_achievements', 'INTEGER DEFAULT 0'),
    ('earned_points', 'INTEGER DEFAULT 0'),
    ('total_points', 'INTEGER DEFAULT 0'),
    ('completion_percentage', 'REAL DEFAULT 0'),
    ('last_synced', 'TEXT'),
    ('steam_app_id', 'TEXT'),
    ('xbox_title_id', 'TEXT'),
    ('source', "TEXT DEFAULT 'ra'"),
]


def _table_exists(cursor, name):
    return cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,),
    ).fetchone() is not None


def _has_column(cursor, table, column):
    cols = {row[1] for row in cursor.execute(f"PRAGMA table_info({table})")}
    return column in cols


def _admin_user_id(cursor):
    if not _table_exists(cursor, 'users'):
        return None
    row = cursor.execute(
        "SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1"
    ).fetchone()
    return row[0] if row else None


def _columns_ddl(cols):
    return ',\n    '.join(f"{name} {defn}" for name, defn in cols)


def _rebuild_game_achievement_progress(cursor, admin_id):
    """Rebuild to (game_id, user_id) composite UNIQUE.

    The inline `game_id INTEGER NOT NULL UNIQUE` on the baseline table can't
    be ALTERed away — full table rebuild is the only way to change it.
    """
    existing = [row[1] for row in cursor.execute("PRAGMA table_info(game_achievement_progress)")]
    target = [c for c, _ in _GAP_COLUMNS]
    shared = [c for c in target if c in existing and c != 'user_id']
    select_cols = ', '.join(shared)
    insert_cols = ', '.join(shared + ['user_id'])

    cursor.execute(f"""
        CREATE TABLE game_achievement_progress_new (
            {_columns_ddl(_GAP_COLUMNS)},
            FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)
    cursor.execute(
        f"INSERT INTO game_achievement_progress_new ({insert_cols}) "
        f"SELECT {select_cols}, ? FROM game_achievement_progress",
        (admin_id,),
    )
    cursor.execute("DROP TABLE game_achievement_progress")
    cursor.execute("ALTER TABLE game_achievement_progress_new RENAME TO game_achievement_progress")
    cursor.execute(
        "CREATE UNIQUE INDEX idx_gap_game_user "
        "ON game_achievement_progress(game_id, user_id)"
    )
    cursor.execute(
        "CREATE INDEX idx_gap_user ON game_achievement_progress(user_id)"
    )


def _rebuild_steam_achievements(cursor, admin_id):
    existing = [row[1] for row in cursor.execute("PRAGMA table_info(steam_achievements)")]
    shared = [c for c in existing if c != 'user_id']
    select_cols = ', '.join(shared)
    insert_cols = ', '.join(shared + ['user_id'])

    cursor.execute("""
        CREATE TABLE steam_achievements_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            apiname TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            icon_url TEXT,
            icon_locked_url TEXT,
            achieved INTEGER DEFAULT 0,
            unlock_time INTEGER DEFAULT 0,
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)
    cursor.execute(
        f"INSERT INTO steam_achievements_new ({insert_cols}) "
        f"SELECT {select_cols}, ? FROM steam_achievements",
        (admin_id,),
    )
    cursor.execute("DROP TABLE steam_achievements")
    cursor.execute("ALTER TABLE steam_achievements_new RENAME TO steam_achievements")
    cursor.execute(
        "CREATE UNIQUE INDEX idx_steam_ach_unique "
        "ON steam_achievements(game_id, apiname, user_id)"
    )
    cursor.execute(
        "CREATE INDEX idx_steam_ach_game ON steam_achievements(game_id)"
    )
    cursor.execute(
        "CREATE INDEX idx_steam_ach_user ON steam_achievements(user_id)"
    )


def _rebuild_xbox_achievements(cursor, admin_id):
    existing = [row[1] for row in cursor.execute("PRAGMA table_info(xbox_achievements)")]
    shared = [c for c in existing if c != 'user_id']
    select_cols = ', '.join(shared)
    insert_cols = ', '.join(shared + ['user_id'])

    cursor.execute("""
        CREATE TABLE xbox_achievements_new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            icon_url TEXT,
            icon_locked_url TEXT,
            gamerscore INTEGER DEFAULT 0,
            achieved INTEGER DEFAULT 0,
            unlock_time TEXT,
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)
    cursor.execute(
        f"INSERT INTO xbox_achievements_new ({insert_cols}) "
        f"SELECT {select_cols}, ? FROM xbox_achievements",
        (admin_id,),
    )
    cursor.execute("DROP TABLE xbox_achievements")
    cursor.execute("ALTER TABLE xbox_achievements_new RENAME TO xbox_achievements")
    cursor.execute(
        "CREATE UNIQUE INDEX idx_xbox_ach_unique "
        "ON xbox_achievements(game_id, achievement_id, user_id)"
    )
    cursor.execute(
        "CREATE INDEX idx_xbox_ach_game ON xbox_achievements(game_id)"
    )
    cursor.execute(
        "CREATE INDEX idx_xbox_ach_user ON xbox_achievements(user_id)"
    )


def apply(conn):
    cursor = conn.cursor()
    cursor.execute("PRAGMA foreign_keys = OFF")

    admin_id = _admin_user_id(cursor)

    def _row_count(table):
        row = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
        return row[0] if row else 0

    # game_achievement_progress: baseline migration 001 always creates this
    # table, so we rebuild it whenever it's still running the pre-31 shape —
    # even on a fresh install where it's empty (no admin backfill needed).
    if _table_exists(cursor, 'game_achievement_progress'):
        if _has_column(cursor, 'game_achievement_progress', 'user_id'):
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_gap_game_user "
                "ON game_achievement_progress(game_id, user_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_gap_user "
                "ON game_achievement_progress(user_id)"
            )
        elif _row_count('game_achievement_progress') > 0 and admin_id is None:
            raise RuntimeError(
                "Migration 009: game_achievement_progress has rows but no admin "
                "user exists to backfill user_id."
            )
        else:
            _rebuild_game_achievement_progress(cursor, admin_id)

    # steam_achievements
    if _table_exists(cursor, 'steam_achievements'):
        if _has_column(cursor, 'steam_achievements', 'user_id'):
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_steam_ach_unique "
                "ON steam_achievements(game_id, apiname, user_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_steam_ach_user "
                "ON steam_achievements(user_id)"
            )
        elif _row_count('steam_achievements') > 0 and admin_id is None:
            raise RuntimeError(
                "Migration 009: steam_achievements has rows but no admin "
                "user exists to backfill user_id."
            )
        else:
            _rebuild_steam_achievements(cursor, admin_id)

    # xbox_achievements
    if _table_exists(cursor, 'xbox_achievements'):
        if _has_column(cursor, 'xbox_achievements', 'user_id'):
            cursor.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_xbox_ach_unique "
                "ON xbox_achievements(game_id, achievement_id, user_id)"
            )
            cursor.execute(
                "CREATE INDEX IF NOT EXISTS idx_xbox_ach_user "
                "ON xbox_achievements(user_id)"
            )
        elif _row_count('xbox_achievements') > 0 and admin_id is None:
            raise RuntimeError(
                "Migration 009: xbox_achievements has rows but no admin "
                "user exists to backfill user_id."
            )
        else:
            _rebuild_xbox_achievements(cursor, admin_id)

    cursor.execute("PRAGMA foreign_keys = ON")

    logger.info(
        "game_achievement_progress / steam_achievements / xbox_achievements "
        "now carry user_id (admin_id=%s)",
        admin_id,
    )
