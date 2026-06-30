# =============================================================================
# Migration 013 — backfill games columns missing from the fresh-install schema
# =============================================================================
# The 001_baseline `games` CREATE TABLE + games_columns ALTER list never
# created the review-score, RetroAchievements, and a handful of metadata
# columns. On the maintainer's long-lived DB these exist because that DB
# pre-dates the migration system (a legacy hand-built schema carried them), but
# a TRULY fresh install — `init_database()` runs only migrations 001..012 —
# produces a `games` table missing all twelve. Any query that SELECTs them then
# raises `sqlite3.OperationalError: no such column` and the route 500s. This is
# the main library card view (routes/games.py api_games_card_data SELECTs
# critic_score / user_score / has_retroachievements / ra_achievement_count),
# game detail, reports, and the scraper UPDATEs that write scores/RA data — i.e.
# a fresh install could not display or scrape its library.
#
# This migration adds each missing column idempotently. On the legacy DB every
# ALTER is a silent no-op (column already present); on a fresh DB it creates
# them with the same types/defaults the legacy schema used, so both converge.
# Discovered 2026-06-30 during the independent-review sweep, once the test suite
# was isolated onto a fresh throwaway DB (which is what surfaced the gap).
# =============================================================================

import logging
import sqlite3

# Strict helper (spec §10/§11): pre-checks PRAGMA table_info instead of
# swallowing every OperationalError, so a real error (bad col_type, locked DB)
# bubbles instead of being silently masked.
from services.migrations._helpers import _add_column_if_missing

logger = logging.getLogger(__name__)


# (column, type-with-default) — types mirror the legacy games schema exactly.
_GAMES_COLUMNS = [
    ('critic_score', 'REAL'),
    ('critic_score_count', 'INTEGER'),
    ('user_score', 'REAL'),
    ('user_score_count', 'INTEGER'),
    ('has_retroachievements', 'INTEGER DEFAULT 0'),
    ('ra_game_id', 'INTEGER'),
    ('ra_achievement_count', 'INTEGER'),
    ('ra_points', 'INTEGER'),
    ('campaign', 'TEXT'),
    ('game_structure', 'TEXT'),
    ('edition', 'TEXT'),
    ('other_platforms', 'TEXT'),
]


# The `systems` table has the same fresh-install gap: the card-data JOIN and
# the system detail / launch paths read s.system_type and s.default_controller_id
# (curated-controller override), neither of which the baseline systems CREATE
# TABLE declares. default_controller_id is a plain INTEGER on the legacy schema
# (no FK), so add it as such — controllers(id) is matched at query time, not by
# a column-level constraint.
_SYSTEMS_COLUMNS = [
    ('system_type', 'TEXT'),
    ('default_controller_id', 'INTEGER'),
]


def apply(conn):
    c = conn.cursor()
    for col_name, col_type in _GAMES_COLUMNS:
        _add_column_if_missing(c, 'games', col_name, col_type)
    for col_name, col_type in _SYSTEMS_COLUMNS:
        _add_column_if_missing(c, 'systems', col_name, col_type)

    # Same fresh-install gap at the table level: `controllers`,
    # `system_controllers`, and `psn_sync_status` are referenced by the code
    # (curated-controller override during scraping, the controllers admin UI,
    # and PSN sync) but were never created by any migration — only the legacy DB
    # has them. CREATE IF NOT EXISTS is a no-op on the legacy DB and creates them
    # on a fresh one. Schemas mirror the legacy DB exactly.
    c.execute("""
        CREATE TABLE IF NOT EXISTS controllers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER,
            name TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            manufacturer TEXT,
            release_year INTEGER,
            description TEXT,
            button_layout TEXT,
            image TEXT,
            FOREIGN KEY (system_id) REFERENCES systems(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS system_controllers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            system_id INTEGER NOT NULL,
            controller_id INTEGER NOT NULL,
            is_default BOOLEAN DEFAULT 0,
            FOREIGN KEY (system_id) REFERENCES systems(id),
            FOREIGN KEY (controller_id) REFERENCES controllers(id),
            UNIQUE(system_id, controller_id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS psn_sync_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT,
            last_full_sync TEXT,
            total_games INTEGER DEFAULT 0,
            sync_in_progress INTEGER DEFAULT 0,
            current_game TEXT,
            current_count INTEGER DEFAULT 0,
            games_to_sync INTEGER DEFAULT 0,
            trophy_level INTEGER DEFAULT 0,
            avatar_url TEXT,
            user_id INTEGER REFERENCES users(id)
        )
    """)
    c.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_psn_sync_status_user_id "
        "ON psn_sync_status(user_id) WHERE user_id IS NOT NULL"
    )

    # Indexes 001_baseline tried to create but skipped because the columns
    # weren't there yet (see its game_indexes try/except) — create them now.
    for idx_name, idx_col in (
        ('idx_games_critic_score', 'critic_score'),
        ('idx_games_user_score', 'user_score'),
        ('idx_games_has_retroachievements', 'has_retroachievements'),
    ):
        try:
            c.execute(f"CREATE INDEX IF NOT EXISTS {idx_name} ON games({idx_col})")
        except sqlite3.OperationalError:
            pass

    logger.info("games score / RetroAchievements / metadata columns ensured")
