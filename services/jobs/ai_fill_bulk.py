# =============================================================================
# RETRODB - Bulk AI Fill Job
# =============================================================================
# Runs AI Fill (services/ai_fill.fill_game) on every game of one system, or
# of all systems, from ROM Tools > Bulk AI Fill. Like the game page's AI
# Fill button it writes straight to the games, under the same fill rules,
# but only to the fields whose switches are on (ai_fill.FIELD_GROUPS).
#
# Games it fills: games with at least one chosen field empty, that AI Fill
# has not done yet (no "ai_fill" entry in their scrape history). So a re-run,
# or a run resumed after a restart, skips the games already done, and nobody
# pays twice for the same game. include_done takes them in again, for a
# field added since, such as sales figures.
# =============================================================================

import logging
import threading
import time
from datetime import datetime, timezone

from services.jobs.base import (
    _get_conn,
    persist_job_start, persist_job_complete,
    resolve_terminal_status,
    acquire_job_singleton_lock, release_singleton_fd,
)

logger = logging.getLogger(__name__)

# The run stops after this many games in a row get no answer: the key, the
# credit or the provider has failed, and every further call would fail too.
MAX_FAILURES_IN_A_ROW = 3

# services/ai_fill.py writes json.dumps() history entries, so the key and
# value are separated by ": ".
_NOT_DONE = """(g.scrape_history IS NULL
                OR g.scrape_history NOT LIKE '%"scrape_mode": "ai_fill"%')"""


def _empty(col):
    # col comes from FIELD_GROUPS, never from a request. A 0 in a number
    # column is "unknown" too (ai_fill skips a 0 answer).
    return f"COALESCE(TRIM(g.{col}), '') IN ('', '0')"


def games_to_fill(conn, system_id, groups=None, include_done=False):
    """The games the run fills, in system then title order.

    groups: the switch keys that are on (ai_fill.FIELD_GROUPS); None for all.
    A game whose title the AI may rename is always a candidate when the
    official-name switch is on: its name is never empty.
    """
    from services.ai_fill import FIELD_GROUPS
    where = [] if include_done else [_NOT_DONE]
    params = []
    if system_id:
        where.append("g.system_id = ?")
        params.append(system_id)
    if groups is not None and 'title' not in groups:
        cols = [c for g in groups for c in FIELD_GROUPS[g]]
        where.append('(' + ' OR '.join(_empty(c) for c in cols) + ')' if cols else '0')
    return [dict(r) for r in conn.execute(f"""
        SELECT g.id, g.title, s.name AS system_name
        FROM games g
        JOIN systems s ON g.system_id = s.id
        WHERE {' AND '.join(where) or '1'}
        ORDER BY s.name, s.id, g.title, g.id
    """, params).fetchall()]


def count_games_to_fill(system_id, groups=None, include_done=False):
    conn = _get_conn()
    try:
        return len(games_to_fill(conn, system_id, groups, include_done))
    finally:
        conn.close()


class AiFillBulkJob:
    """Fill empty game metadata from the AI, one game at a time."""

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
        self.total = 0
        self.success_count = 0   # games that got at least one field
        self.failed_count = 0    # games the AI gave no answer for
        self.skipped_count = 0   # games the AI answered with nothing new
        self.current_title = ""
        self.system_name = ""
        self.start_time = None
        self.error_message = None

    def start(self, system_id=None, groups=None, include_done=False):
        """Start a run over one system, or every system when None, filling
        the fields under the switch keys `groups` (None: every field)."""
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'An AI fill run is already running'}
            singleton_fd = acquire_job_singleton_lock('ai_fill_bulk')
            if singleton_fd is None:
                return {'success': False,
                        'error': 'An AI fill run is already running on another worker process.'}
            self.reset()
            self._singleton_fd = singleton_fd
            self.job_id = f"ai_fill_bulk_{int(time.time())}"
            self.running = True
            self.start_time = datetime.now(timezone.utc).isoformat()

        self._thread = threading.Thread(target=self._worker, args=(system_id, groups, include_done), daemon=True)
        self._thread.start()
        return {'success': True, 'job_id': self.job_id}

    def resume_from_params(self, params, progress=None):
        """Restart an interrupted run. Games already filled are skipped."""
        params = params or {}
        return self.start(params.get('system_id'), params.get('groups'),
                          params.get('include_done', False)).get('success', False)

    def cancel(self):
        with self._lock:
            if self.running and not self.completed:
                self.cancelled = True
                return {'success': True}
            return {'success': False, 'error': 'No AI fill run to cancel'}

    def get_status(self):
        with self._lock:
            processed = self.success_count + self.failed_count + self.skipped_count
            total = self.total
            return {
                'job_id': self.job_id,
                'running': self.running,
                'completed': self.completed,
                'cancelled': self.cancelled,
                'processed': processed,
                'processing': min(processed + 1, total) if total else 0,
                'total': total,
                'percent': int(processed / total * 100) if total else 0,
                'success': self.success_count,
                'failed': self.failed_count,
                'skipped': self.skipped_count,
                'current_game': self.current_title,
                'system_name': self.system_name,
                'return_url': '/tools/official-names',
                'error': self.error_message,
            }

    def _worker(self, system_id, groups, include_done):
        persist_id = None
        status, error = 'completed', None
        try:
            from services.ai_fill import columns_for, fill_game, load_game
            fields = columns_for(groups)
            conn = _get_conn()
            try:
                games = games_to_fill(conn, system_id, groups, include_done)
            finally:
                conn.close()
            with self._lock:
                self.total = len(games)
            persist_id = persist_job_start('ai_fill_bulk', {
                'system_id': system_id, 'groups': groups,
                'include_done': include_done, 'total': len(games)})

            in_a_row = 0
            for game in games:
                with self._lock:
                    if self.cancelled:
                        break
                    self.current_title = game['title']
                    self.system_name = game['system_name']
                row = load_game(game['id'])
                filled = fill_game(row, fields) if row else []
                with self._lock:
                    if filled is None:
                        self.failed_count += 1
                    elif filled:
                        self.success_count += 1
                    else:
                        self.skipped_count += 1
                in_a_row = in_a_row + 1 if filled is None else 0
                if in_a_row >= MAX_FAILURES_IN_A_ROW:
                    raise RuntimeError(f'The AI gave no answer for {in_a_row} games in a row')
            with self._lock:
                status = resolve_terminal_status(self.cancelled)
        except Exception as e:
            # Games already filled keep what they got.
            logger.error(f"AI fill run stopped: {e}", exc_info=True)
            status, error = 'failed', str(e)

        with self._lock:
            self.completed = True
            self.running = False
            self.error_message = error
            logger.info(f"AI fill run: {self.success_count} filled, {self.skipped_count} "
                        f"unchanged, {self.failed_count} without an answer, of "
                        f"{self.total} ({status})")
        release_singleton_fd(self)
        if persist_id:
            persist_job_complete(persist_id, status=status, error=error)
