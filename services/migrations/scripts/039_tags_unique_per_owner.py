# =============================================================================
# Migration 039 — a tag name is unique per owner, not install-wide (PASS-59-241)
# =============================================================================
# 001 made tags.name UNIQUE across everyone; 005 added owner_id but could not
# drop that constraint. So a second user's tag of the same name failed with
# a 500. SQLite cannot drop a column constraint, so the table is rebuilt with
# UNIQUE(owner_id, name).
#
# game_tags is rebuilt alongside it. Dropping tags while any table points at
# it would, with foreign keys on, cascade-delete every game's tags, so both
# wait in plain copies meanwhile. Ids are kept, so every link survives.
# =============================================================================

from services.migrations._helpers import _table_exists


def apply(conn):
    cursor = conn.cursor()
    if not _table_exists(cursor, 'tags') or not _table_exists(cursor, 'game_tags'):
        return
    # Real installs create users first; a bare database has none to point at.
    owner_ref = ' REFERENCES users(id)' if _table_exists(cursor, 'users') else ''

    # Both tables wait in copies with no foreign keys, and are created anew
    # without ALTER TABLE RENAME, which re-checks every trigger in the schema.
    cursor.execute("CREATE TABLE tags_keep AS "
                   "SELECT id, name, color, created_at, owner_id FROM tags")
    cursor.execute("CREATE TABLE game_tags_keep AS SELECT game_id, tag_id FROM game_tags")
    cursor.execute("DROP TABLE game_tags")
    cursor.execute("DROP TABLE tags")
    cursor.execute(f"""
        CREATE TABLE tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL COLLATE NOCASE,
            color TEXT DEFAULT '#4cc9f0',
            created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
            owner_id INTEGER{owner_ref},
            UNIQUE (owner_id, name)
        )
    """)
    # Old installs can hold rows a delete should have taken: tags of a deleted
    # person, links to a deleted game or tag. Copying them back fails with
    # foreign keys on and the app will not start, so they are left behind,
    # as deleting the person, game or tag would have done (011's pattern).
    owner_ok = (' WHERE owner_id IS NULL OR owner_id IN (SELECT id FROM users)'
                if owner_ref else '')
    cursor.execute("INSERT INTO tags (id, name, color, created_at, owner_id) "
                   "SELECT id, name, color, created_at, owner_id FROM tags_keep"
                   + owner_ok)
    cursor.execute("""
        CREATE TABLE game_tags (
            game_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            PRIMARY KEY (game_id, tag_id),
            FOREIGN KEY (game_id) REFERENCES games(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
    """)
    cursor.execute("INSERT INTO game_tags (game_id, tag_id) "
                   "SELECT game_id, tag_id FROM game_tags_keep "
                   "WHERE game_id IN (SELECT id FROM games) "
                   "AND tag_id IN (SELECT id FROM tags)")
    cursor.execute("DROP TABLE game_tags_keep")
    cursor.execute("DROP TABLE tags_keep")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tags_owner_id ON tags(owner_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_tags_game ON game_tags(game_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_game_tags_tag ON game_tags(tag_id)")
