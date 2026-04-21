# =============================================================================
# RETRODB - Database Initialization & Migrations
# =============================================================================
# Schema creation, ALTER TABLE column adds, index creation, and one-shot
# data migrations. Runs on every app import (idempotent).
# =============================================================================

import logging
import os
import sqlite3

import config
from services.auth import hash_password

logger = logging.getLogger(__name__)


def init_database():
    """Initialize database if it doesn't exist."""
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)

    conn = sqlite3.connect(config.DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS systems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            folder TEXT NOT NULL UNIQUE,
            logo TEXT
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            publisher TEXT,
            developer TEXT,
            release_date TEXT,
            genre TEXT,
            rating TEXT,
            esrb_rating TEXT,
            pegi_rating TEXT,
            players INTEGER,
            modes TEXT,
            description TEXT,
            boxart TEXT,
            boxart_3d TEXT,
            screenshots TEXT,
            fanart TEXT,
            video TEXT,
            manual TEXT,
            region TEXT,
            franchise TEXT,
            similar_games TEXT,
            playtime_estimate TEXT,
            controller_support TEXT,
            save_type TEXT,
            sort_title TEXT,
            rom_path TEXT NOT NULL UNIQUE,
            scraped BOOLEAN DEFAULT 0,
            is_bonus_disc BOOLEAN DEFAULT 0,
            parent_game_id INTEGER,
            FOREIGN KEY(system_id) REFERENCES systems(id),
            FOREIGN KEY(parent_game_id) REFERENCES games(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS publishers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screenscraper_id TEXT UNIQUE,
            name TEXT NOT NULL
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS developers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            screenscraper_id TEXT UNIQUE,
            name TEXT NOT NULL
        )
    """)

    new_columns = [
        ('fanart', 'TEXT'),
        ('video', 'TEXT'),
        ('manual', 'TEXT'),
        ('region', 'TEXT'),
        ('franchise', 'TEXT'),
        ('similar_games', 'TEXT'),
        ('playtime_estimate', 'TEXT'),
        ('controller_support', 'TEXT'),
        ('save_type', 'TEXT'),
        ('scrape_history', 'TEXT'),
        ('completion_status', 'TEXT DEFAULT "not_started"'),
        ('file_size', 'INTEGER'),
        ('last_viewed', 'TEXT'),
        ('sort_title', 'TEXT'),
        ('hltb_match_name', 'TEXT'),
        ('hltb_match_platform', 'TEXT'),
        ('hltb_match_confidence', 'REAL'),
        ('boxart_3d', 'TEXT'),
        ('clz_title', 'TEXT'),
        ('perspective', 'TEXT'),
        ('dimension', 'TEXT'),
        ('created_at', 'TEXT'),
        ('last_bulk_scraped', 'TEXT'),
        ('steam_app_id', 'TEXT'),
        ('xbox_title_id', 'TEXT'),
        ('psn_npwr_id', 'TEXT'),
        ('cero_rating', 'TEXT'),
        ('usk_rating', 'TEXT'),
        ('acb_rating', 'TEXT'),
        ('fpb_rating', 'TEXT'),
        ('grac_rating', 'TEXT'),
        ('classind_rating', 'TEXT'),
    ]
    for col_name, col_type in new_columns:
        try:
            c.execute(f"ALTER TABLE games ADD COLUMN {col_name} {col_type}")
            logger.info(f"Added new column: {col_name}")
        except sqlite3.OperationalError:
            pass

    # Backfill clz_title for existing CLZ imports
    try:
        c.execute("""
            UPDATE games
            SET clz_title = SUBSTR(rom_path,
                LENGTH('clz_import/') + INSTR(SUBSTR(rom_path, LENGTH('clz_import/') + 1), '/') + 1)
            WHERE rom_path LIKE 'clz_import/%/%'
              AND (clz_title IS NULL OR clz_title = '')
        """)
        if c.rowcount > 0:
            logger.info(f"Backfilled clz_title for {c.rowcount} existing CLZ imports")
    except Exception as e:
        logger.warning(f"Could not backfill clz_title: {e}")

    c.execute("""
        CREATE TABLE IF NOT EXISTS game_achievement_progress (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL UNIQUE,
            ra_game_id INTEGER,
            earned_achievements INTEGER DEFAULT 0,
            total_achievements INTEGER DEFAULT 0,
            earned_points INTEGER DEFAULT 0,
            total_points INTEGER DEFAULT 0,
            completion_percentage REAL DEFAULT 0,
            last_synced TEXT,
            FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)

    for col_name, col_type in [
        ('steam_app_id', 'TEXT'),
        ('xbox_title_id', 'TEXT'),
        ('source', "TEXT DEFAULT 'ra'"),
    ]:
        try:
            c.execute(f"ALTER TABLE game_achievement_progress ADD COLUMN {col_name} {col_type}")
            logger.info(f"Added {col_name} column to game_achievement_progress")
        except sqlite3.OperationalError:
            pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS normalization_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            from_value TEXT NOT NULL,
            to_value TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(category, from_value)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS dropdown_options (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT NOT NULL,
            value TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            UNIQUE(category, value)
        )
    """)

    perspective_defaults = [
        ('perspective', 'First-Person', 1),
        ('perspective', 'Isometric', 2),
        ('perspective', 'Side-Scroller', 3),
        ('perspective', 'Third-Person', 4),
        ('perspective', 'Top-Down', 5),
    ]
    for cat, val, order in perspective_defaults:
        try:
            c.execute("INSERT OR IGNORE INTO dropdown_options (category, value, sort_order) VALUES (?, ?, ?)",
                      (cat, val, order))
        except sqlite3.OperationalError:
            pass

    dimension_defaults = [
        ('dimension', '2D', 1),
        ('dimension', '2.5D', 2),
        ('dimension', '3D', 3),
        ('dimension', 'AR', 4),
        ('dimension', 'FMV', 5),
        ('dimension', 'Pseudo-3D', 6),
        ('dimension', 'VR', 7),
    ]
    for cat, val, order in dimension_defaults:
        try:
            c.execute("INSERT OR IGNORE INTO dropdown_options (category, value, sort_order) VALUES (?, ?, ?)",
                      (cat, val, order))
        except sqlite3.OperationalError:
            pass

    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_achievement_progress_game ON game_achievement_progress(game_id)")
    except sqlite3.OperationalError:
        pass

    game_indexes = [
        ("idx_games_system_id", "system_id"),
        ("idx_games_is_bonus_disc", "is_bonus_disc"),
        ("idx_games_sort_title", "sort_title"),
        ("idx_games_parent_game_id", "parent_game_id"),
        ("idx_games_scraped", "scraped"),
        ("idx_games_title", "title"),
        ("idx_games_completion_status", "completion_status"),
        ("idx_games_has_retroachievements", "has_retroachievements"),
        ("idx_games_genre", "genre"),
        ("idx_games_developer", "developer"),
        ("idx_games_publisher", "publisher"),
        ("idx_games_franchise", "franchise"),
        ("idx_games_release_date", "release_date"),
        ("idx_games_critic_score", "critic_score"),
        ("idx_games_user_score", "user_score"),
        ("idx_games_file_size", "file_size"),
        ("idx_games_players", "players"),
        ("idx_games_created_at", "created_at"),
        ("idx_games_steam_app_id", "steam_app_id"),
        ("idx_games_xbox_title_id", "xbox_title_id"),
        ("idx_games_psn_npwr_id", "psn_npwr_id"),
        ("idx_games_rom_path", "rom_path"),
    ]
    for idx_name, idx_col in game_indexes:
        try:
            c.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON games({idx_col})")
        except sqlite3.OperationalError:
            pass

    composite_indexes = [
        ("idx_games_system_scraped", "system_id, scraped"),
        ("idx_games_system_bonus", "system_id, is_bonus_disc"),
        ("idx_games_system_bonus_scraped", "system_id, is_bonus_disc, scraped"),
    ]
    for idx_name, idx_cols in composite_indexes:
        try:
            c.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON games({idx_cols})")
        except sqlite3.OperationalError:
            pass

    try:
        c.execute("ALTER TABLE psn_games ADD COLUMN trophies_synced INTEGER DEFAULT 0")
        logger.info("Added trophies_synced column to psn_games")
    except sqlite3.OperationalError:
        pass

    for col_name, col_type in [("trophy_level", "INTEGER DEFAULT 0"), ("avatar_url", "TEXT")]:
        try:
            c.execute(f"ALTER TABLE psn_sync_status ADD COLUMN {col_name} {col_type}")
            logger.info(f"Added {col_name} column to psn_sync_status")
        except sqlite3.OperationalError:
            pass

    hltb_columns = [
        ("hltb_id", "INTEGER"),
        ("hltb_title", "TEXT"),
        ("hltb_main", "TEXT"),
        ("hltb_extra", "TEXT"),
        ("hltb_complete", "TEXT")
    ]
    for col_name, col_type in hltb_columns:
        try:
            c.execute(f"ALTER TABLE psn_games ADD COLUMN {col_name} {col_type}")
            logger.info(f"Added {col_name} column to psn_games")
        except sqlite3.OperationalError:
            pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS job_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            status TEXT DEFAULT 'running',
            progress TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            error_message TEXT,
            params TEXT
        )
    """)

    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_job_queue_status ON job_queue(status)")
    except sqlite3.OperationalError:
        pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE COLLATE NOCASE,
            color TEXT DEFAULT '#4cc9f0',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS game_tags (
            game_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (game_id, tag_id),
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS lists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            icon TEXT DEFAULT '📋',
            sort_order INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS list_games (
            list_id INTEGER NOT NULL,
            game_id INTEGER NOT NULL,
            position INTEGER DEFAULT 0,
            added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            PRIMARY KEY (list_id, game_id),
            FOREIGN KEY (list_id) REFERENCES lists(id) ON DELETE CASCADE,
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS wishlist (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            system_name TEXT,
            notes TEXT,
            priority INTEGER DEFAULT 2,
            added_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            game_id INTEGER,
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE SET NULL
        )
    """)

    # Wishlist metadata columns — populated by the wishlist scraper so each
    # entry can carry boxart + descriptive metadata without living in the
    # main games table. system_id is nullable so users can wishlist games
    # for systems not yet in RetroDB (e.g. future PlayStation 6 titles).
    wishlist_columns = [
        ('system_id', 'INTEGER'),
        ('boxart', 'TEXT'),
        ('boxart_3d', 'TEXT'),
        ('fanart', 'TEXT'),
        ('screenshots', 'TEXT'),
        ('video', 'TEXT'),
        ('manual', 'TEXT'),
        ('description', 'TEXT'),
        ('release_date', 'TEXT'),
        ('developer', 'TEXT'),
        ('publisher', 'TEXT'),
        ('genre', 'TEXT'),
        ('franchise', 'TEXT'),
        ('modes', 'TEXT'),
        ('players', 'INTEGER'),
        ('esrb_rating', 'TEXT'),
        ('pegi_rating', 'TEXT'),
        ('critic_score', 'REAL'),
        ('critic_score_count', 'INTEGER'),
        ('user_score', 'REAL'),
        ('user_score_count', 'INTEGER'),
        ('source', 'TEXT'),
        ('source_id', 'TEXT'),
        ('scrape_status', "TEXT DEFAULT 'unscraped'"),
        ('scraped_at', 'TEXT'),
    ]
    for col_name, col_type in wishlist_columns:
        try:
            c.execute(f"ALTER TABLE wishlist ADD COLUMN {col_name} {col_type}")
            logger.info(f"Added {col_name} column to wishlist")
        except sqlite3.OperationalError:
            pass

    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_wishlist_scrape_status ON wishlist(scrape_status)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_wishlist_system_id ON wishlist(system_id)")
    except sqlite3.OperationalError:
        pass

    c.execute("""
        CREATE TABLE IF NOT EXISTS collector_trophies (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            icon TEXT NOT NULL,
            tier TEXT NOT NULL DEFAULT 'bronze',
            category TEXT NOT NULL DEFAULT 'general',
            threshold INTEGER DEFAULT 0,
            earned_at TEXT,
            progress INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS system_museum (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL UNIQUE,
            history TEXT,
            summary TEXT,
            top_games TEXT,
            generated_at TEXT,
            generated_by TEXT,
            FOREIGN KEY (system_id) REFERENCES systems(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS steam_achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            apiname TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            icon_url TEXT,
            icon_locked_url TEXT,
            achieved INTEGER DEFAULT 0,
            unlock_time INTEGER DEFAULT 0,
            UNIQUE(game_id, apiname),
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS xbox_achievements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER NOT NULL,
            achievement_id TEXT NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            icon_url TEXT,
            icon_locked_url TEXT,
            gamerscore INTEGER DEFAULT 0,
            achieved INTEGER DEFAULT 0,
            unlock_time TEXT,
            UNIQUE(game_id, achievement_id),
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE
        )
    """)

    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_game_tags_game ON game_tags(game_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_game_tags_tag ON game_tags(tag_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_list_games_list ON list_games(list_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_list_games_game ON list_games(game_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_wishlist_priority ON wishlist(priority)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_collector_trophies_tier ON collector_trophies(tier)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_system_museum_system ON system_museum(system_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_steam_ach_game ON steam_achievements(game_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_xbox_ach_game ON xbox_achievements(game_id)")
    except sqlite3.OperationalError:
        pass

    _migrate_genre_canonical(c)
    _migrate_pegi_format(c)

    c.execute("PRAGMA optimize")

    conn.commit()
    conn.close()
    logger.info("Database initialized")


def ensure_user_tables():
    """Ensure user-related tables exist."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE COLLATE NOCASE,
            display_name TEXT,
            password_hash TEXT,
            role TEXT NOT NULL DEFAULT 'viewer',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            last_login TEXT,
            is_active BOOLEAN DEFAULT 1,
            force_password_change BOOLEAN DEFAULT 0
        )
    """)

    try:
        cursor.execute("ALTER TABLE users ADD COLUMN force_password_change BOOLEAN DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE,
            rpcs3_trophy_path TEXT DEFAULT '',
            ra_username TEXT DEFAULT '',
            ra_api_key TEXT DEFAULT '',
            theme_preference TEXT DEFAULT 'default',
            items_per_page INTEGER DEFAULT 50,
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)

    try:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN avatar TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute("ALTER TABLE user_settings ADD COLUMN timezone TEXT DEFAULT 'UTC'")
    except sqlite3.OperationalError:
        pass

    cursor.execute("SELECT id FROM users WHERE role = 'admin' LIMIT 1")
    admin_exists = cursor.fetchone()

    if not admin_exists:
        default_password_hash = hash_password('admin')
        cursor.execute("""
            INSERT INTO users (username, display_name, password_hash, role, force_password_change)
            VALUES (?, ?, ?, ?, ?)
        """, ('admin', 'Administrator', default_password_hash, 'admin', 1))
        admin_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO user_settings (user_id)
            VALUES (?)
        """, (admin_id,))

        logger.info("Created default admin user (username: admin, password: admin)")

    conn.commit()
    conn.close()


def _migrate_genre_canonical(cursor):
    """Migrate existing genre values to canonical schema forms. Idempotent."""
    migrations = [
        ('FPS', 'First-Person-Shooter'),
        ("Shoot 'em Up", 'Shoot-em-up'),
        ("Shoot'em Up", 'Shoot-em-up'),
        ("Beat 'em Up", 'Beat-em-up'),
        ("Beat'em Up", 'Beat-em-up'),
        ('Hack and Slash', 'Hack-n-Slash'),
        ('Third-Person Shooter', 'Shooter'),
        ('Light Gun', 'Light-Gun'),
        ('Tower Defense', 'Tower-Defence'),
        ('Battle Royale', 'Battle-Royale'),
        ('Board Game', 'Board-Card'),
        ('Card Game', 'Board-Card'),
        ('Visual Novel', 'Visual-Novel'),
        ('Life Simulation', 'Life-Simulation'),
        ('City Builder', 'City-Builder'),
        ('Survival Horror', 'Survival-Horror'),
        ('Psychological Horror', 'Psychological-Horror'),
        ('Flight Simulator', 'Flight'),
        ('Kart Racing', 'Racing'),
        ('Tactical RPG', 'Strategy'),
    ]
    try:
        for old_val, new_val in migrations:
            cursor.execute(
                "UPDATE games SET genre = REPLACE(genre, ?, ?) WHERE genre LIKE ?",
                (old_val, new_val, f'%{old_val}%')
            )
        logger.info("Genre canonical migration completed")
    except Exception as e:
        logger.warning(f"Genre canonical migration skipped: {e}")


def _migrate_pegi_format(cursor):
    """Migrate bare PEGI numbers (e.g. '12') to 'PEGI 12' format. Idempotent."""
    try:
        for num in ['3', '7', '12', '16', '18']:
            cursor.execute(
                "UPDATE games SET pegi_rating = ? WHERE pegi_rating = ?",
                (f'PEGI {num}', num)
            )
        logger.info("PEGI format migration completed")
    except Exception as e:
        logger.warning(f"PEGI format migration skipped: {e}")
