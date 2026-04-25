# =============================================================================
# Migration 007 — user_id on psn_games / psn_trophies (Pass 31.1)
# =============================================================================
# Pre-Pass-31, `psn_games` was keyed on `npwr_id UNIQUE`. Two PSN-connected
# RetroDB users shared a single row per game — whichever synced last
# overwrote the other's earned-trophy counts (`ON CONFLICT(npwr_id) DO
# UPDATE SET earned_platinum = excluded.earned_platinum, …`). Every route
# that reads the table ignored ownership and returned everyone's library to
# every caller. OWASP A01.
#
# This migration:
#   (a) ensures both tables exist at all (see PSN schema history note below),
#   (b) adds `user_id INTEGER NOT NULL` + `UNIQUE(npwr_id, user_id)` on
#       psn_games (previously UNIQUE on npwr_id),
#   (c) adds `user_id INTEGER NOT NULL` on psn_trophies plus a derived
#       UNIQUE(psn_game_id, trophy_id) index,
#   (d) backfills legacy rows to the first admin user — matching the single-
#       tenant pre-Pass-27 assumption that "the admin owns everything."
#
# Why a full table rebuild: SQLite can't DROP an inline column-level UNIQUE
# constraint, only recreate the table around it. Steps follow the canonical
# 12-step procedure from https://sqlite.org/lang_altertable.html#otheralter.
# FOREIGN KEYS are left OFF for the duration since the connection factory
# never turns them ON anyway; belt-and-braces still disables them here so
# the rebuild is safe even if a future init enables FKs globally.
#
# PSN schema history: `psn_games` / `psn_trophies` / `psn_sync_status` were
# created by an ad-hoc migration in `services.psn_sync` that pre-dates the
# versioned migration runner (Pass 20.1). That module was removed; fresh
# installs have never had those tables. This migration adopts responsibility
# for creating them on a fresh install AND for rebuilding them with user_id
# on a legacy install — so PSN sync works end-to-end regardless of whether
# the installer came through the pre- or post-Pass-31 path.
# =============================================================================

import logging

logger = logging.getLogger(__name__)


_PSN_GAMES_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('npwr_id', 'TEXT NOT NULL'),
    ('user_id', 'INTEGER NOT NULL'),
    ('title', 'TEXT'),
    ('platform', 'TEXT'),
    ('icon_url', 'TEXT'),
    ('defined_bronze', 'INTEGER DEFAULT 0'),
    ('defined_silver', 'INTEGER DEFAULT 0'),
    ('defined_gold', 'INTEGER DEFAULT 0'),
    ('defined_platinum', 'INTEGER DEFAULT 0'),
    ('earned_bronze', 'INTEGER DEFAULT 0'),
    ('earned_silver', 'INTEGER DEFAULT 0'),
    ('earned_gold', 'INTEGER DEFAULT 0'),
    ('earned_platinum', 'INTEGER DEFAULT 0'),
    ('progress', 'INTEGER DEFAULT 0'),
    ('last_updated', 'TEXT'),
    ('created_at', 'TEXT DEFAULT CURRENT_TIMESTAMP'),
    ('linked_game_id', 'INTEGER REFERENCES games(id)'),
    ('total_platinum', 'INTEGER DEFAULT 0'),
    ('total_gold', 'INTEGER DEFAULT 0'),
    ('total_silver', 'INTEGER DEFAULT 0'),
    ('total_bronze', 'INTEGER DEFAULT 0'),
    ('total_trophies', 'INTEGER DEFAULT 0'),
    ('earned_trophies', 'INTEGER DEFAULT 0'),
    ('first_trophy_earned', 'TEXT'),
    ('last_trophy_earned', 'TEXT'),
    ('hltb_id', 'INTEGER'),
    ('hltb_title', 'TEXT'),
    ('hltb_main', 'TEXT'),
    ('hltb_extra', 'TEXT'),
    ('hltb_complete', 'TEXT'),
    ('trophies_synced', 'INTEGER DEFAULT 0'),
]

_PSN_TROPHIES_COLUMNS = [
    ('id', 'INTEGER PRIMARY KEY AUTOINCREMENT'),
    ('psn_game_id', 'INTEGER NOT NULL'),
    ('user_id', 'INTEGER NOT NULL'),
    ('trophy_id', 'INTEGER'),
    ('name', 'TEXT'),
    ('detail', 'TEXT'),
    ('trophy_type', 'TEXT'),
    ('icon_url', 'TEXT'),
    ('earned', 'INTEGER DEFAULT 0'),
    ('earned_date', 'TEXT'),
    ('group_id', "TEXT DEFAULT 'default'"),
    ('group_name', "TEXT DEFAULT 'Base Game'"),
    ('rarity', 'REAL'),
    ('rarity_label', 'TEXT'),
    ('description', 'TEXT'),
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


def _create_psn_games_fresh(cursor):
    ddl = f"""
        CREATE TABLE psn_games (
            {_columns_ddl(_PSN_GAMES_COLUMNS)}
        )
    """
    cursor.execute(ddl)
    cursor.execute(
        "CREATE UNIQUE INDEX idx_psn_games_npwr_user ON psn_games(npwr_id, user_id)"
    )
    cursor.execute("CREATE INDEX idx_psn_games_user ON psn_games(user_id)")
    cursor.execute("CREATE INDEX idx_psn_games_linked ON psn_games(linked_game_id)")


def _create_psn_trophies_fresh(cursor):
    ddl = f"""
        CREATE TABLE psn_trophies (
            {_columns_ddl(_PSN_TROPHIES_COLUMNS)},
            FOREIGN KEY (psn_game_id) REFERENCES psn_games(id)
        )
    """
    cursor.execute(ddl)
    cursor.execute(
        "CREATE UNIQUE INDEX idx_psn_trophies_unique "
        "ON psn_trophies(psn_game_id, trophy_id)"
    )
    cursor.execute(
        "CREATE INDEX idx_psn_trophies_game ON psn_trophies(psn_game_id)"
    )
    cursor.execute(
        "CREATE INDEX idx_psn_trophies_user ON psn_trophies(user_id)"
    )


def _rebuild_psn_games(cursor, admin_id):
    """Drop UNIQUE(npwr_id), add user_id, land UNIQUE(npwr_id, user_id)."""
    # Snapshot column set so we only copy what both shapes share.
    existing = [row[1] for row in cursor.execute("PRAGMA table_info(psn_games)")]
    target = [c for c, _ in _PSN_GAMES_COLUMNS]
    shared = [c for c in target if c in existing and c != 'user_id']
    select_cols = ', '.join(shared)
    insert_cols = ', '.join(shared + ['user_id'])

    cursor.execute(f"""
        CREATE TABLE psn_games_new (
            {_columns_ddl(_PSN_GAMES_COLUMNS)}
        )
    """)
    # admin_id is the fallback owner for every pre-migration row; multi-user
    # installs can later re-assign ownership by re-syncing each connected
    # account.
    cursor.execute(
        f"INSERT INTO psn_games_new ({insert_cols}) "
        f"SELECT {select_cols}, ? FROM psn_games",
        (admin_id,),
    )
    cursor.execute("DROP TABLE psn_games")
    cursor.execute("ALTER TABLE psn_games_new RENAME TO psn_games")
    cursor.execute(
        "CREATE UNIQUE INDEX idx_psn_games_npwr_user ON psn_games(npwr_id, user_id)"
    )
    cursor.execute("CREATE INDEX idx_psn_games_user ON psn_games(user_id)")
    cursor.execute("CREATE INDEX idx_psn_games_linked ON psn_games(linked_game_id)")


def _rebuild_psn_trophies(cursor, admin_id):
    existing = [row[1] for row in cursor.execute("PRAGMA table_info(psn_trophies)")]
    target = [c for c, _ in _PSN_TROPHIES_COLUMNS]
    shared = [c for c in target if c in existing and c != 'user_id']
    select_cols = ', '.join(shared)
    insert_cols = ', '.join(shared + ['user_id'])

    cursor.execute(f"""
        CREATE TABLE psn_trophies_new (
            {_columns_ddl(_PSN_TROPHIES_COLUMNS)},
            FOREIGN KEY (psn_game_id) REFERENCES psn_games(id)
        )
    """)
    cursor.execute(
        f"INSERT INTO psn_trophies_new ({insert_cols}) "
        f"SELECT {select_cols}, ? FROM psn_trophies",
        (admin_id,),
    )
    cursor.execute("DROP TABLE psn_trophies")
    cursor.execute("ALTER TABLE psn_trophies_new RENAME TO psn_trophies")
    cursor.execute(
        "CREATE UNIQUE INDEX idx_psn_trophies_unique "
        "ON psn_trophies(psn_game_id, trophy_id)"
    )
    cursor.execute(
        "CREATE INDEX idx_psn_trophies_game ON psn_trophies(psn_game_id)"
    )
    cursor.execute(
        "CREATE INDEX idx_psn_trophies_user ON psn_trophies(user_id)"
    )


def apply(conn):
    cursor = conn.cursor()

    # Defer FK enforcement until COMMIT. `PRAGMA foreign_keys = OFF` is a
    # no-op inside a transaction (SQLite docs: FK enforcement state cannot
    # change mid-txn), but `defer_foreign_keys = ON` works inside a txn and
    # is auto-reset at txn end. Lets the rebuild drop and recreate referenced
    # tables atomically without spurious immediate-FK violations.
    cursor.execute("PRAGMA defer_foreign_keys = ON")

    admin_id = _admin_user_id(cursor)

    # psn_games
    if not _table_exists(cursor, 'psn_games'):
        # Fresh install — table has never existed. Create with the new shape.
        _create_psn_games_fresh(cursor)
    elif _has_column(cursor, 'psn_games', 'user_id'):
        # Partial run (someone ran a patched version of this migration manually)
        # — ensure indexes exist and move on.
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_psn_games_npwr_user "
            "ON psn_games(npwr_id, user_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_psn_games_user ON psn_games(user_id)"
        )
    else:
        # Legacy install — rebuild to add user_id and change UNIQUE.
        if admin_id is None:
            # A legacy install with rows but no admin user is impossible under
            # the normal ensure_user_tables() init path, but refuse the
            # rebuild rather than silently leaving rows with a NULL owner.
            raise RuntimeError(
                "Migration 007: legacy psn_games table exists but no admin user "
                "is available to backfill ownership. Create an admin user first."
            )
        _rebuild_psn_games(cursor, admin_id)

    # psn_trophies
    if not _table_exists(cursor, 'psn_trophies'):
        _create_psn_trophies_fresh(cursor)
    elif _has_column(cursor, 'psn_trophies', 'user_id'):
        cursor.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_psn_trophies_unique "
            "ON psn_trophies(psn_game_id, trophy_id)"
        )
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_psn_trophies_user ON psn_trophies(user_id)"
        )
    else:
        if admin_id is None:
            raise RuntimeError(
                "Migration 007: legacy psn_trophies table exists but no admin "
                "user is available to backfill ownership."
            )
        _rebuild_psn_trophies(cursor, admin_id)

    # defer_foreign_keys auto-resets at COMMIT — no explicit restoration needed.

    logger.info(
        "psn_games / psn_trophies now carry user_id; npwr_id uniqueness is "
        "scoped per user (admin_id=%s)",
        admin_id,
    )
