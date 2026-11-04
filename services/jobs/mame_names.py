# =============================================================================
# RETRODB - MAME Names Job (PASS-59-227)
# =============================================================================
# Reads the lists the user chose, then gives each arcade game its real name,
# year, maker and category. The rules are in services/mame_names.py.
# =============================================================================

import logging
import threading
import time
from datetime import datetime, timezone

from services import mame_names
from services.jobs.base import (
    _get_conn, _commit_with_retry,
    persist_job_start, persist_job_complete, resolve_terminal_status,
    acquire_job_singleton_lock, release_singleton_fd,
)

logger = logging.getLogger(__name__)

_COMMIT_EVERY = 200


class MameNamesJob:
    """Name the games in the arcade folders from MAME's own lists."""

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
        self.reading = False
        self.current_index = 0
        self.total_games = 0
        self.named_count = 0
        self.updated_count = 0
        self.not_listed_count = 0
        self.error_message = None
        self.start_time = None

    def start(self, list_paths, category_path=None):
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'already_running'}
            singleton_fd = acquire_job_singleton_lock('mame_names')
            if singleton_fd is None:
                return {'success': False, 'error': 'already_running'}
            self.reset()
            self._singleton_fd = singleton_fd
            self.job_id = f"mame_names_{int(time.time())}"
            self.running = True
            self.reading = True
            self.start_time = datetime.now(timezone.utc).isoformat()
        self._thread = threading.Thread(
            target=self._worker, args=(list_paths, category_path), daemon=True)
        self._thread.start()
        return {'success': True, 'job_id': self.job_id}

    def cancel(self):
        with self._lock:
            if self.running and not self.completed:
                self.cancelled = True
                return {'success': True}
            return {'success': False, 'error': 'not_running'}

    def get_status(self):
        with self._lock:
            return {
                'job_id': self.job_id,
                'running': self.running,
                'completed': self.completed,
                'cancelled': self.cancelled,
                'reading': self.reading,
                'current': self.current_index,
                'total': self.total_games,
                'named': self.named_count,
                'updated': self.updated_count,
                'not_listed': self.not_listed_count,
                'error': self.error_message,
            }

    def _stopping(self):
        with self._lock:
            return self.cancelled

    def _apply(self, conn, rows, machines, categories):
        for i, row in enumerate(rows):
            if self._stopping():
                return
            name = mame_names.set_name(row)
            machine = machines.get(name)
            category = categories.get(name)
            changes = mame_names.changes_for(row, machine or {}, category)
            if changes:
                mame_names.apply_changes(conn, row['id'], changes)
                if (i + 1) % _COMMIT_EVERY == 0:
                    _commit_with_retry(conn)
            with self._lock:
                self.current_index = i + 1
                self.not_listed_count += machine is None
                self.named_count += 'title' in changes
                self.updated_count += bool(changes)

    def _worker(self, list_paths, category_path):
        persist_id = None
        try:
            persist_id = persist_job_start('mame_names', {})
            conn = _get_conn()
            try:
                rows = mame_names.arcade_rows(conn)
                with self._lock:
                    self.total_games = len(rows)
                wanted = {mame_names.set_name(r) for r in rows}
                machines = {}
                for path in list_paths:
                    if not self._stopping():
                        mame_names.read_machines(path, wanted, machines, self._stopping)
                categories = (mame_names.read_categories(category_path, wanted)
                              if category_path and not self._stopping() else {})
                with self._lock:
                    self.reading = False
                self._apply(conn, rows, machines, categories)
                _commit_with_retry(conn)
            finally:
                conn.close()
            from services.game_query import invalidate_filter_cache
            invalidate_filter_cache()
            with self._lock:
                self.completed = True
                self.running = False
                final_status = resolve_terminal_status(self.cancelled)
                logger.info(f"MAME names: {self.named_count} named, {self.updated_count} changed, "
                            f"{self.not_listed_count} not in the lists")
            release_singleton_fd(self)
            persist_job_complete(persist_id, status=final_status)
        except Exception as e:
            logger.error(f"MAME names error: {e}", exc_info=True)
            with self._lock:
                self.completed = True
                self.running = False
                self.reading = False
                self.error_message = str(e)
            release_singleton_fd(self)
            if persist_id:
                persist_job_complete(persist_id, status='failed', error=str(e))
