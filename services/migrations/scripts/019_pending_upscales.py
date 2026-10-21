# =============================================================================
# Migration 019 — games whose images still wait for upscaling (PASS-59-130)
# =============================================================================
# Additive: `pending_upscales` holds one row per game a scrape saved with its
# small images as downloaded. services/upscale_queue.py's background worker
# upscales them and deletes the row, so a row left at shutdown is resumed on
# the next start (docs/specs/image-pipeline.md §5.1).
# =============================================================================


def apply(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_upscales (
            game_id   INTEGER PRIMARY KEY,
            queued_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
