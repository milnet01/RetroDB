# =============================================================================
# RETRODB - Background upscaling of scraped images (PASS-59-130)
# =============================================================================
# A scrape runs inside upscale_later(): its small images are saved as
# downloaded, and the game is listed in `pending_upscales` once the apply
# ends. One background thread then upscales each listed game's images and
# removes the row. The list lives in the database, so work left at shutdown
# resumes on the next start. Contract: docs/specs/image-pipeline.md §5.1.
# =============================================================================

import contextlib
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone

from services.image_utils import (
    _make_responsive_variants,
    defer_upscale,
    standardize_downloaded_image,
)

logger = logging.getLogger(__name__)

# The per-game media columns a scrape fills. Fanart is never standardized.
_MEDIA_FIELDS = ('boxart', 'boxart_3d', 'screenshots')

# How long the idle worker sleeps before looking at the table again. An
# enqueue in this process wakes it at once; this catches rows another process
# (a script run outside the server) added.
_IDLE_SECONDS = 60

_wake = threading.Event()
_started = False
_start_lock = threading.Lock()


def _connect():
    from scraper.base_scraper import get_scraper_conn
    return get_scraper_conn()


def enqueue(game_id):
    """List `game_id` for upscaling. A game already listed gets a fresh
    `queued_at`, so a worker part-way through it keeps the row."""
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        conn = _connect()
        try:
            conn.execute(
                "INSERT OR REPLACE INTO pending_upscales (game_id, queued_at) VALUES (?, ?)",
                (game_id, stamp))
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning(f"Upscale queue: could not list game {game_id}: {e}")
        return
    _wake.set()


@contextlib.contextmanager
def upscale_later(game_id):
    """Defer upscaling for the images a scrape of `game_id` saves, and list
    the game for the background worker when the scrape ends."""
    token = defer_upscale.set(True)
    try:
        yield
    finally:
        defer_upscale.reset(token)
        enqueue(game_id)


def pending_status(game_id=None):
    """(games still listed, whether `game_id` is one of them), for the
    PASS-59-153 indicator. (0, False) when the table cannot be read."""
    try:
        conn = _connect()
        try:
            count = conn.execute("SELECT COUNT(*) FROM pending_upscales").fetchone()[0]
            listed = game_id is not None and conn.execute(
                "SELECT 1 FROM pending_upscales WHERE game_id = ?", (game_id,)
            ).fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error as e:
        logger.warning(f"Upscale queue: could not read the list: {e}")
        return 0, False
    return count, listed


def _media_files(conn, game_id):
    """(path, image_type) for each media file `game_id` names."""
    import config
    row = conn.execute(
        f"SELECT {', '.join(_MEDIA_FIELDS)} FROM games WHERE id = ?", (game_id,)
    ).fetchone()
    if row is None:
        return []
    files = []
    for field in _MEDIA_FIELDS:
        for name in (row[field] or '').split(','):
            name = name.strip()
            if name:
                files.append((os.path.join(config.IMAGE_PATH, field, name), field))
    return files


def process_game(game_id, queued_at):
    """Standardize every image `game_id` names, then drop its row unless a
    newer scrape listed the game again meanwhile."""
    started = time.monotonic()
    conn = _connect()
    try:
        files = [(p, t) for p, t in _media_files(conn, game_id) if os.path.exists(p)]
        for path, image_type in files:
            try:
                standardize_downloaded_image(path, image_type)
                _make_responsive_variants(path, image_type)
            except Exception as e:
                logger.warning(f"Upscale queue: {path} failed: {e}")
        conn.execute("DELETE FROM pending_upscales WHERE game_id = ? AND queued_at = ?",
                     (game_id, queued_at))
        conn.commit()
    finally:
        conn.close()
    logger.info(f"Upscale queue: game {game_id}, {len(files)} images, "
                f"{time.monotonic() - started:.1f}s")


def _next_row():
    conn = _connect()
    try:
        return conn.execute(
            "SELECT game_id, queued_at FROM pending_upscales ORDER BY queued_at LIMIT 1"
        ).fetchone()
    finally:
        conn.close()


def run_pending():
    """Process listed games until the table is empty. Returns how many ran."""
    done = 0
    while True:
        row = _next_row()
        if row is None:
            return done
        process_game(row['game_id'], row['queued_at'])
        done += 1


def start_upscale_worker():
    """Start the background worker. Idempotent within a process."""
    global _started
    with _start_lock:
        if _started:
            return
        _started = True

    def _loop():
        while True:
            _wake.clear()
            try:
                run_pending()
            except Exception as e:  # never let the daemon die on one bad game
                logger.error("Upscale queue tick failed: %s", e, exc_info=True)
            _wake.wait(_IDLE_SECONDS)

    threading.Thread(target=_loop, name="upscale-queue", daemon=True).start()
    logger.info("Upscale queue worker started")
