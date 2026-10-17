# =============================================================================
# RETRODB - Museum Controller Image Fetch Job
# =============================================================================
# Background job for the Museum's "Fetch All Images": searches, downloads and
# background-removes an image for each of a system's controllers that has
# none. PASS-59-116 moved it out of the web request, which it held for a
# network round trip plus a one-second pause per controller.
#
# Not persisted for resume: one system's controllers take a minute or two,
# and a restart loses nothing a second click does not redo.
# =============================================================================

import threading
import time
import logging

from services.jobs.base import (
    _get_conn, _commit_with_retry, shutdown_requested,
    acquire_job_singleton_lock, release_singleton_fd,
)

logger = logging.getLogger(__name__)


class MuseumImageFetchJob:
    """Fetches missing controller images for one system."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.reset()

    def reset(self):
        """Reset job state."""
        self.job_id = None
        self.running = False
        self.completed = False
        self.cancelled = False
        self.system_id = None
        self.current_index = 0
        self.total = 0
        self.current_item = ""
        self.success_count = 0
        self.failed_count = 0
        self.skipped_count = 0
        self.error_message = None

    def get_status(self):
        """Return current job status."""
        with self._lock:
            processed = self.success_count + self.failed_count + self.skipped_count
            return {
                'job_id': self.job_id,
                'running': self.running,
                'completed': self.completed,
                'cancelled': self.cancelled,
                'system_id': self.system_id,
                'current': self.current_index,
                'processed': processed,
                'total': self.total,
                'percent': int(processed / self.total * 100) if self.total else 0,
                'current_item': self.current_item,
                'success': self.success_count,
                'failed': self.failed_count,
                'skipped': self.skipped_count,
                'error': self.error_message,
            }

    def start(self, system_id):
        """Start fetching images for `system_id`'s controllers."""
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'Image fetch already in progress'}
            fd = acquire_job_singleton_lock('museum_images')
            if fd is None:
                return {'success': False,
                        'error': 'Image fetch is already running on another worker process.'}
            self.reset()
            self._singleton_fd = fd
            self.job_id = f"museum_images_{int(time.time())}"
            self.system_id = system_id
            self.running = True
        self._thread = threading.Thread(target=self._worker, args=(system_id,), daemon=True)
        self._thread.start()
        return {'success': True, 'job_id': self.job_id}

    def cancel(self):
        """Cancel the running fetch."""
        with self._lock:
            if self.running and not self.completed:
                self.cancelled = True
                return {'success': True}
            return {'success': False, 'error': 'No running image fetch to cancel'}

    def _worker(self, system_id):
        # Lazy import: the fetch helpers live with the Museum routes.
        from routes.museum import (
            _fetch_and_process_image, _get_removebg_key, _propagate_controller_image,
        )
        conn = _get_conn()
        try:
            controllers = conn.execute(
                """SELECT c.id, c.name, c.manufacturer, c.image FROM controllers c
                   JOIN system_controllers sc ON c.id = sc.controller_id
                   WHERE sc.system_id = ?""",
                (system_id,)).fetchall()
            system = conn.execute("SELECT name FROM systems WHERE id = ?",
                                  (system_id,)).fetchone()
            system_name = system['name'] if system else ''
            removebg_key = _get_removebg_key()
            with self._lock:
                self.total = len(controllers)

            for i, ctrl in enumerate(controllers):
                with self._lock:
                    if self.cancelled:
                        break
                    self.current_index = i
                    self.current_item = ctrl['name']
                if ctrl['image']:
                    with self._lock:
                        self.skipped_count += 1
                    continue
                try:
                    result = _fetch_and_process_image(
                        ctrl['id'], ctrl['name'], ctrl['manufacturer'] or '',
                        system_name, removebg_key)
                    if result:
                        conn.execute("UPDATE controllers SET image = ? WHERE id = ?",
                                     (result, ctrl['id']))
                        _commit_with_retry(conn)
                        _propagate_controller_image(conn, ctrl['id'], result)
                    with self._lock:
                        if result:
                            self.success_count += 1
                        else:
                            self.failed_count += 1
                except Exception as e:
                    logger.warning(f"museum_images: controller {ctrl['id']} failed: {e}")
                    with self._lock:
                        self.failed_count += 1
                shutdown_requested.wait(1)  # Rate limit the image search
        except Exception as e:
            logger.error(f"museum_images worker error: {e}")
            with self._lock:
                self.error_message = str(e)
        finally:
            conn.close()
            with self._lock:
                self.completed = True
                self.running = False
            release_singleton_fd(self)
