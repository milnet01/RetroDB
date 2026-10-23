# =============================================================================
# Migration 021 — official names and the title lock (PASS-59-159)
# =============================================================================
# Additive (docs/specs/PASS-59-159-official-names.md §4.1):
#   * `games.title_locked` — 1 means no scraper writes `title` or `sort_title`;
#   * `title_proposals` — one AI-proposed name per game, pending or rejected.
#
# A trigger, not ON DELETE CASCADE, removes a deleted game's proposal: it fires
# on every connection, whether or not that connection turned foreign keys on.
# =============================================================================

from services.migrations._helpers import _add_column_if_missing, _table_exists


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'games'):
        return
    _add_column_if_missing(cursor, 'games', 'title_locked',
                           'INTEGER NOT NULL DEFAULT 0')
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS title_proposals (
            game_id          INTEGER PRIMARY KEY,
            old_title        TEXT NOT NULL,
            proposed_title   TEXT NOT NULL,
            old_title_region TEXT,
            status           TEXT NOT NULL DEFAULT 'pending'
                             CHECK (status IN ('pending', 'rejected')),
            created_at       TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    cursor.execute("""
        CREATE TRIGGER IF NOT EXISTS trg_games_delete_title_proposal
        AFTER DELETE ON games
        BEGIN
            DELETE FROM title_proposals WHERE game_id = OLD.id;
        END
    """)
