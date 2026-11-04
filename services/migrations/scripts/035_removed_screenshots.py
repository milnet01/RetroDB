# =============================================================================
# Migration 035 — screenshots the user removed (PASS-59-222)
# =============================================================================
# A deleted screenshot's dHash, so a later scrape does not download or copy
# the same picture back. Hex text: a 64-bit dHash can exceed SQLite's signed
# INTEGER.
# =============================================================================


def apply(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS removed_screenshots (
            game_id INTEGER NOT NULL REFERENCES games(id) ON DELETE CASCADE,
            dhash TEXT NOT NULL,
            removed_at TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (game_id, dhash)
        )
    """)
