# =============================================================================
# RETRODB - Build 3D Boxes job (PASS-59-326 §4.5)
# =============================================================================
# ROM Tools' Build 3D Boxes: builds the 3D box of every game scraped before
# scrapes built one. One game at a time, on a lowered priority, so the server
# stays quick. A game with an imported box, or a built one whose scans have not
# changed, is passed over, so a second run costs little.
# Spec: docs/specs/PASS-59-326-auto-3d-box.md.
# =============================================================================

import logging
import os
import threading
import time
from datetime import datetime, timezone

from services.jobs.base import (
    _get_conn, acquire_job_singleton_lock, persist_job_complete, persist_job_progress,
    persist_job_start, release_singleton_fd, resolve_terminal_status, shutdown_requested,
)

logger = logging.getLogger(__name__)

_NICENESS = 10      # how much the worker thread lowers its own priority (Linux)


def _candidates():
    """(id, title, system name) of every game the job may build, by id."""
    from services.box3d.build import PLATFORMS
    folders = sorted(PLATFORMS)
    conn = _get_conn()
    try:
        return conn.execute(f"""
            SELECT g.id, g.title, s.name FROM games g JOIN systems s ON s.id = g.system_id
            WHERE s.folder IN ({','.join('?' * len(folders))})
              AND ((g.boxart IS NOT NULL AND g.boxart != '') OR g.box_scans IS NOT NULL)
              AND (g.box_faces IS NULL OR NOT json_valid(g.box_faces)
                   OR CASE WHEN json_valid(g.box_faces)
                           THEN json_extract(g.box_faces, '$.source') END = 'auto')
            ORDER BY g.id
        """, folders).fetchall()
    finally:
        conn.close()


def _cut_out_discs():
    """Take every stored disc or cartridge picture off its backdrop: those
    downloaded before downloads did it. Returns how many changed."""
    from services import box_scans
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT box_scans FROM games WHERE box_scans LIKE '%\\_media\\_%' ESCAPE '\\'"
        ).fetchall()
    finally:
        conn.close()
    changed = 0
    for (value,) in rows:
        if shutdown_requested.is_set():
            break
        changed += box_scans.cut_out_stored(value)
    return changed


def _lower_priority():
    """Lower this thread's CPU priority; Linux gives each thread its own."""
    if not hasattr(os, 'setpriority') or not hasattr(threading, 'get_native_id'):
        return
    try:
        tid = threading.get_native_id()
        os.setpriority(os.PRIO_PROCESS, tid, os.getpriority(os.PRIO_PROCESS, tid) + _NICENESS)
    except OSError as e:
        logger.debug(f'Build 3D boxes: could not lower priority: {e}')


class BoxBuildJob:
    """Build the 3D box of every game that has scans and no box yet."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.reset()

    def reset(self):
        self.running = False
        self.cancelled = False
        self.completed = False
        self.current_index = 0
        self.total = 0
        self.current_game = ''
        self.current_system = ''
        self.counts = {}
        self.start_time = None
        self.end_time = None
        self.error_message = None

    def start(self):
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'Building 3D boxes is already running'}
            singleton_fd = acquire_job_singleton_lock('box_build')
            if singleton_fd is None:
                return {'success': False,
                        'error': 'Building 3D boxes is already running on another worker process.'}
            self.reset()
            self._singleton_fd = singleton_fd
            self.running = True
            self.start_time = datetime.now(timezone.utc).isoformat()
            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()
        return {'success': True, 'message': 'Building 3D boxes started'}

    def cancel(self):
        with self._lock:
            if not self.running:
                return {'success': False, 'error': 'No job running'}
            self.cancelled = True
        return {'success': True, 'message': 'Cancellation requested'}

    def get_status(self):
        with self._lock:
            counts = dict(self.counts)
            return {
                'running': self.running, 'cancelled': self.cancelled,
                'completed': self.completed,
                'current': self.current_index, 'total': self.total,
                'percent': round(self.current_index / self.total * 100) if self.total else 0,
                'current_game': self.current_game, 'current_system': self.current_system,
                'success_count': counts.get('built', 0),
                'skipped': sum(n for k, n in counts.items() if k not in ('built', 'failed')),
                'failed': counts.get('failed', 0),
                'start_time': self.start_time, 'end_time': self.end_time,
                'error_message': self.error_message,
            }

    def _worker(self):
        from services.box3d.build import build_for_game
        _lower_priority()
        persist_id = None
        last_persist = time.time()
        try:
            persist_id = persist_job_start('box_build', {})
            cut = _cut_out_discs()
            if cut:
                logger.info(f'Build 3D boxes: took {cut} disc or cartridge pictures off their backdrop')
            games = _candidates()
            with self._lock:
                self.total = len(games)
            for i, (game_id, title, system) in enumerate(games):
                with self._lock:
                    if self.cancelled:
                        break
                    self.current_index = i + 1
                    self.current_game, self.current_system = title or '', system or ''
                if shutdown_requested.is_set():
                    break
                outcome = build_for_game(game_id)
                with self._lock:
                    self.counts[outcome] = self.counts.get(outcome, 0) + 1
                    progress = {'current': i + 1, 'total': self.total, **self.counts}
                if persist_id and time.time() - last_persist >= 30:
                    persist_job_progress(persist_id, progress)
                    last_persist = time.time()
        except Exception as e:
            logger.error(f'Build 3D boxes worker error: {e}')
            with self._lock:
                self.error_message = str(e)
            if persist_id:
                persist_job_complete(persist_id, status='failed', error=str(e))
                persist_id = None
        finally:
            with self._lock:
                self.running = False
                self.completed = True
                self.end_time = datetime.now(timezone.utc).isoformat()
                final_status = resolve_terminal_status(self.cancelled)
                counts = dict(self.counts)
            release_singleton_fd(self)
            if persist_id:
                persist_job_complete(persist_id, status=final_status)
            logger.info(f'Build 3D boxes finished: {counts}')
