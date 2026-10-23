# =============================================================================
# RETRODB - Official Names Job (PASS-59-159)
# =============================================================================
# Asks the configured AI for each game's official name in its ROM's region,
# in batches, and stores one proposal per game in `title_proposals`. It never
# writes `games`: a name changes only when the user accepts it on
# /tools/official-names (docs/specs/PASS-59-159-official-names.md §4.4).
#
# Games it asks about: every game with a ROM, except locked titles and games
# with a pending proposal. So a re-run, or a run resumed after a restart,
# skips the games already answered.
# =============================================================================

import logging
import threading
import time
from datetime import datetime, timezone

from services.jobs.base import (
    _get_conn, _commit_with_retry,
    persist_job_start, persist_job_complete,
    resolve_terminal_status,
    acquire_job_singleton_lock, release_singleton_fd,
)

logger = logging.getLogger(__name__)


def _games_to_ask(conn, system_id):
    """Games the run asks about, grouped by system in system order."""
    where_system = "AND g.system_id = ?" if system_id else ""
    params = (system_id,) if system_id else ()
    return [dict(r) for r in conn.execute(f"""
        SELECT g.id, g.title, g.rom_path, g.region,
               s.id AS system_id, s.name AS system_name
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE g.rom_path IS NOT NULL AND g.rom_path != ''
          AND g.rom_path NOT LIKE 'clz_import/%'
          AND g.title_locked = 0
          AND NOT EXISTS (SELECT 1 FROM title_proposals p
                          WHERE p.game_id = g.id AND p.status = 'pending')
          {where_system}
        ORDER BY s.name, s.id, g.title, g.id
    """, params).fetchall()]


def store_answer(conn, game, answer):
    """Store one AI answer as a pending proposal, or nothing (§4.4).
    Returns True when a pending row was written."""
    proposed = answer.get('official_title')
    if not proposed or proposed == game['title']:
        return False
    rejected = conn.execute(
        "SELECT 1 FROM title_proposals WHERE game_id = ? AND status = 'rejected' "
        "AND proposed_title = ?", (game['id'], proposed)).fetchone()
    if rejected:
        return False
    conn.execute("""
        INSERT INTO title_proposals
            (game_id, old_title, proposed_title, old_title_region, status, created_at)
        VALUES (?, ?, ?, ?, 'pending', datetime('now'))
        ON CONFLICT(game_id) DO UPDATE SET
            old_title = excluded.old_title,
            proposed_title = excluded.proposed_title,
            old_title_region = excluded.old_title_region,
            status = 'pending',
            created_at = excluded.created_at
    """, (game['id'], game['title'], proposed, answer.get('old_title_region')))
    return True


class OfficialNamesJob:
    """Collect AI-proposed official names for review."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.reset()

    def reset(self):
        self.job_id = None
        self.running = False
        self.completed = False
        self.cancelled = False
        self.current_index = 0
        self.total_games = 0
        self.proposals = 0
        self.current_system = ""
        self.start_time = None
        self.error_message = None

    def start(self, system_id=None):
        """Start a run over one system, or every system when None."""
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'An official names run is already running'}
            singleton_fd = acquire_job_singleton_lock('official_names')
            if singleton_fd is None:
                return {'success': False,
                        'error': 'An official names run is already running on another worker process.'}
            self.reset()
            self._singleton_fd = singleton_fd
            self.job_id = f"official_names_{int(time.time())}"
            self.running = True
            self.start_time = datetime.now(timezone.utc).isoformat()

        self._thread = threading.Thread(target=self._worker, args=(system_id,), daemon=True)
        self._thread.start()
        return {'success': True, 'job_id': self.job_id}

    def resume_from_params(self, params, progress=None):
        """Restart an interrupted run. Games with a pending proposal are
        skipped, so the restarted run picks up where the old one stopped."""
        return self.start((params or {}).get('system_id')).get('success', False)

    def cancel(self):
        with self._lock:
            if self.running and not self.completed:
                self.cancelled = True
                return {'success': True}
            return {'success': False, 'error': 'No official names run to cancel'}

    def get_status(self):
        with self._lock:
            percent = int(self.current_index / self.total_games * 100) if self.total_games else 0
            return {
                'job_id': self.job_id,
                'running': self.running,
                'completed': self.completed,
                'cancelled': self.cancelled,
                'current': self.current_index,
                'total': self.total_games,
                'percent': percent,
                'proposals': self.proposals,
                'current_system': self.current_system,
                'error': self.error_message,
            }

    def _batches(self, games):
        from scraper.scrape_ai import OFFICIAL_NAMES_BATCH
        batch = []
        for game in games:
            if batch and (len(batch) == OFFICIAL_NAMES_BATCH
                          or game['system_id'] != batch[0]['system_id']):
                yield batch
                batch = []
            batch.append(game)
        if batch:
            yield batch

    def _worker(self, system_id):
        persist_id = None
        status, error = 'completed', None
        try:
            from scraper.scrape_ai import propose_official_names
            conn = _get_conn()
            try:
                games = _games_to_ask(conn, system_id)
                with self._lock:
                    self.total_games = len(games)
                persist_id = persist_job_start('official_names', {
                    'system_id': system_id, 'total': len(games)})

                for batch in self._batches(games):
                    with self._lock:
                        if self.cancelled:
                            break
                        self.current_system = batch[0]['system_name']
                    answers = propose_official_names(batch[0]['system_name'], [
                        {'title': g['title'], 'rom_file': g['rom_path'], 'region': g['region']}
                        for g in batch])
                    made = sum(store_answer(conn, g, a) for g, a in zip(batch, answers))
                    _commit_with_retry(conn)
                    with self._lock:
                        self.current_index += len(batch)
                        self.proposals += made
            finally:
                conn.close()
            with self._lock:
                status = resolve_terminal_status(self.cancelled)
        except Exception as e:
            # A provider error stops the run; proposals already stored stay.
            logger.error(f"Official names run stopped: {e}", exc_info=True)
            status, error = 'failed', str(e)

        with self._lock:
            self.completed = True
            self.running = False
            self.error_message = error
            logger.info(f"Official names run: {self.current_index}/{self.total_games} "
                        f"games asked, {self.proposals} proposals ({status})")
        release_singleton_fd(self)
        if persist_id:
            persist_job_complete(persist_id, status=status, error=error)
