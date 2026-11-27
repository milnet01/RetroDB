# =============================================================================
# Migration 050 — the games a bulk scrape failed or skipped, with the reason
# =============================================================================
# PASS-59-338. Additive. One row per failed or skipped game of the latest bulk
# scrape (and the jobs queued behind it); a fresh bulk scrape empties it. The
# Bulk Scraping window and the job card list these, linking each game.
# =============================================================================


def apply(conn):
    conn.cursor().execute("""
        CREATE TABLE IF NOT EXISTS bulk_scrape_outcomes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id      TEXT,
            game_id     INTEGER,
            title       TEXT,
            outcome     TEXT NOT NULL,
            reason      TEXT NOT NULL,
            detail      TEXT,
            created_at  TEXT
        )
    """)
