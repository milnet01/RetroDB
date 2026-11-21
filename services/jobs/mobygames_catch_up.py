# =============================================================================
# RETRODB - MobyGames catch-up job (PASS-59-183 §4.6)
# =============================================================================
# MobyGames allows a few hundred requests an hour. A scrape that finds the
# hour spent goes on without it and lists the game in mobygames_pending. This
# job asks MobyGames about each listed game, oldest first, once the stop ends,
# through the same fill-only scrape with MobyGames as its only source.
#
# A game leaves the list when it is asked, found or not. The job waits out an
# hour's stop, or a pause while the server is not answering, and carries on, so a long list empties by itself; it ends when
# the list is empty, when MobyGames refuses the key (waiting will not help),
# or at shutdown. The list is in the database, so the next start carries on.
# =============================================================================

import logging
import threading
import time
from datetime import datetime, timezone

from scraper import service_limits
from services.jobs.base import (
    _get_conn, acquire_job_singleton_lock, release_singleton_fd, shutdown_requested,
)

logger = logging.getLogger(__name__)

_LONGEST_WAIT = 60  # seconds; the stop is looked at again at least this often


def add_pending(game_id):
    """List a game MobyGames could not be asked about this hour."""
    if not game_id:
        return
    conn = _get_conn()
    try:
        conn.execute("INSERT OR IGNORE INTO mobygames_pending (game_id, added_at) VALUES (?, ?)",
                     (game_id, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()


def _next_pending():
    """(game_id, system folder) of the oldest listed game, or None."""
    conn = _get_conn()
    try:
        row = conn.execute("""
            SELECT p.game_id, s.folder FROM mobygames_pending p
            JOIN games g ON g.id = p.game_id JOIN systems s ON s.id = g.system_id
            ORDER BY p.added_at, p.game_id LIMIT 1
        """).fetchone()
        return (row[0], row[1]) if row else None
    finally:
        conn.close()


def _take(game_id):
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM mobygames_pending WHERE game_id = ?", (game_id,))
        conn.commit()
    finally:
        conn.close()


class MobyGamesCatchUpJob:
    """Ask MobyGames about the games a scrape passed over."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.running = False
        self.cancelled = False
        self.asked_count = 0

    def start_if_pending(self):
        """Start the job when games are listed and it is not running. Never raises:
        it runs after every scrape."""
        try:
            if not self.running and _next_pending():
                self.start()
        except Exception as e:
            logger.warning(f"MobyGames catch-up not started: {e}")

    def start(self):
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'already_running'}
            fd = acquire_job_singleton_lock('mobygames_catch_up')
            if fd is None:
                return {'success': False, 'error': 'already_running'}
            self._singleton_fd = fd
            self.running = True
            self.cancelled = False
            self.asked_count = 0
        self._thread = threading.Thread(target=self._worker, daemon=True,
                                        name='mobygames-catch-up')
        self._thread.start()
        return {'success': True}

    def cancel(self):
        with self._lock:
            if not self.running:
                return {'success': False, 'error': 'not_running'}
            self.cancelled = True
            return {'success': True}

    def get_status(self):
        with self._lock:
            return {'running': self.running, 'asked': self.asked_count}

    def _worker(self):
        try:
            self.run_pending()
        except Exception as e:
            logger.error(f"MobyGames catch-up failed: {e}", exc_info=True)
        finally:
            with self._lock:
                self.running = False
            release_singleton_fd(self)

    def _stopping(self):
        with self._lock:
            return self.cancelled or shutdown_requested.is_set()

    def run_pending(self):
        """Ask about each listed game in turn; returns when the job ends."""
        from scraper.hybrid_scraper import apply_hybrid_metadata
        while not self._stopping():
            stop = service_limits.stopped(service_limits.MOBYGAMES)
            if stop:
                if stop['reason'] not in (service_limits.LIMIT_REACHED, service_limits.UNAVAILABLE):
                    logger.info("MobyGames catch-up ends: MobyGames refused the key")
                    return
                shutdown_requested.wait(min(max(stop['until'] - time.time(), 1), _LONGEST_WAIT))
                continue
            listed = _next_pending()
            if not listed:
                return
            game_id, folder = listed
            # Off the list first: if the hour runs out before the request, the
            # scrape lists the game again.
            _take(game_id)
            try:
                apply_hybrid_metadata(game_id, 'none', None, folder,
                                      mark_scraped=False, only_source='mobygames')
            except Exception as e:
                logger.warning(f"MobyGames catch-up for game {game_id} failed: {e}")
            with self._lock:
                self.asked_count += 1
