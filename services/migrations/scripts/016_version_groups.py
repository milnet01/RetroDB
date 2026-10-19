# =============================================================================
# Migration 016 — regional versions of a game (PASS-59-106)
# =============================================================================
# Two or more `games` rows on one system can be linked as versions of one game
# (docs/specs/PASS-59-106-regional-versions.md §4.1). Additive only:
#   * `version_groups` — one row per linked group;
#   * `games.version_group_id` — the group a row belongs to, or NULL;
#   * `version_link_rejections` — pairs the user said are not versions, so a
#     suggestion never pairs them again;
#   * `games.igdb_id` / `games.screenscraper_id` — suggestion signals, filled by
#     scrapes and the Backfill Alternate Titles job.
#
# RetroDB never turns on `PRAGMA foreign_keys`, so the REFERENCES clauses below
# document intent and enforce nothing. The triggers do the work instead: a
# group never keeps fewer than two members when a row is deleted, becomes a
# bonus disc, or moves to another system; and a deleted game's rejections go
# with it. Links themselves are written only by services/version_groups.py.
# =============================================================================

import logging

from services.migrations._helpers import _add_column_if_missing, _table_exists

logger = logging.getLogger(__name__)

# Drop a group left with fewer than two members. `{gid}` is OLD/NEW's column.
_DISSOLVE_SMALL_GROUP = """
    UPDATE games SET version_group_id = NULL
     WHERE version_group_id = {gid}
       AND (SELECT COUNT(*) FROM games WHERE version_group_id = {gid}) < 2;
    DELETE FROM version_groups
     WHERE id = {gid}
       AND NOT EXISTS (SELECT 1 FROM games WHERE version_group_id = {gid});
"""


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'games'):
        return

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS version_groups (
            id         INTEGER PRIMARY KEY,
            created_at TEXT NOT NULL
        )
    """)
    _add_column_if_missing(cursor, 'games', 'version_group_id',
                           'INTEGER REFERENCES version_groups(id) ON DELETE SET NULL')
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_games_version_group "
                   "ON games(version_group_id)")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS version_link_rejections (
            game_a     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            game_b     INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            PRIMARY KEY (game_a, game_b),
            CHECK (game_a < game_b)
        )
    """)
    _add_column_if_missing(cursor, 'games', 'igdb_id', 'INTEGER')
    _add_column_if_missing(cursor, 'games', 'screenscraper_id', 'INTEGER')

    cursor.execute(f"""
        CREATE TRIGGER IF NOT EXISTS trg_games_delete_version_group
        AFTER DELETE ON games
        WHEN OLD.version_group_id IS NOT NULL
        BEGIN
            {_DISSOLVE_SMALL_GROUP.format(gid='OLD.version_group_id')}
        END
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_games_delete_version_rejections
        AFTER DELETE ON games
        BEGIN
            DELETE FROM version_link_rejections
             WHERE game_a = OLD.id OR game_b = OLD.id;
        END
    """)
    # A bonus disc is never a member, and every member shares one system.
    cursor.execute(f"""
        CREATE TRIGGER IF NOT EXISTS trg_games_leave_version_group
        AFTER UPDATE OF is_bonus_disc, system_id ON games
        WHEN NEW.version_group_id IS NOT NULL
         AND (NEW.is_bonus_disc = 1 OR NEW.system_id IS NOT OLD.system_id)
        BEGIN
            UPDATE games SET version_group_id = NULL WHERE id = NEW.id;
            {_DISSOLVE_SMALL_GROUP.format(gid='NEW.version_group_id')}
        END
    """)
    logger.info("version_groups schema added")
