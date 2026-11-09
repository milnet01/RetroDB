# =============================================================================
# RETRODB - RetroAchievements job queue (PASS-59-268)
# =============================================================================
# RA Sync and RA Refresh share one RetroAchievements account, so only one runs
# at a time. A request made while either is running waits here, on the server,
# and starts when both are idle: whichever page or device asked, and whether
# or not any page is open. Each waiting entry also gets a `job_queue` row, so a
# restart offers it back on the dashboard like any other queued job.
# =============================================================================

import itertools
import logging
import threading
import time

from services.jobs.base import persist_job_queued, remove_queued_job

logger = logging.getLogger(__name__)

POLL_SECONDS = 2


class RAQueue:
    """Waiting RA Sync / RA Refresh requests, first come first served."""

    def __init__(self, sync_job, refresh_job):
        self._sync = sync_job
        self._refresh = refresh_job
        self._lock = threading.Lock()
        self._items = []
        self._ids = itertools.count(1)
        self._thread = None

    def busy(self):
        """True while an RA Sync or RA Refresh is running."""
        for job in (self._sync, self._refresh):
            status = job.get_status()
            if status.get('running') and not status.get('completed'):
                return True
        return False

    def add(self, kind, system_id, system_name, user_id=None):
        """Queue `kind` ('sync' or 'refresh') for `system_id` (None: every
        system, refresh only). A request already waiting is not added twice.
        Returns the entry, with its 1-based `position`."""
        with self._lock:
            for item in self._items:
                if (item['kind'], item['system_id'], item['user_id']) == (kind, system_id, user_id):
                    return self._public(item)
            params = {'system_id': system_id, 'system_name': system_name}
            if user_id is not None:
                params['user_id'] = user_id
            item = {
                'id': next(self._ids), 'kind': kind, 'system_id': system_id,
                'system_name': system_name, 'user_id': user_id,
                'row_id': persist_job_queued(f'ra_{kind}', params=params),
            }
            self._items.append(item)
            if self._thread is None:
                self._thread = threading.Thread(target=self._watch, name='ra-queue', daemon=True)
                self._thread.start()
            return self._public(item)

    def items(self):
        """Every waiting entry, in the order they will run."""
        with self._lock:
            return [self._public(item) for item in self._items]

    def get(self, item_id):
        with self._lock:
            for item in self._items:
                if item['id'] == item_id:
                    return self._public(item)
        return None

    def cancel(self, item_id):
        """Drop a waiting entry. False when it is not waiting (any more)."""
        with self._lock:
            for item in self._items:
                if item['id'] == item_id:
                    self._items.remove(item)
                    break
            else:
                return False
        remove_queued_job(item['row_id'])
        return True

    def start_next(self):
        """Start the first waiting entry if nothing is running. Returns the
        entry started, or None. Called by the watcher; public for tests."""
        with self._lock:
            if not self._items or self.busy():
                return None
            item = self._items.pop(0)
        if item['kind'] == 'sync':
            result = self._sync.start(item['system_id'], system_name=item['system_name'],
                                      user_id=item['user_id'])
        else:
            result = self._refresh.start(system_id=item['system_id'],
                                         system_name=item['system_name'])
        if not result.get('success'):
            # Another worker process took the account first: wait again.
            if 'already running' in str(result.get('error', '')):
                with self._lock:
                    self._items.insert(0, item)
                return None
            logger.warning('Queued RA %s for %s did not start: %s',
                           item['kind'], item['system_name'], result.get('error'))
        else:
            logger.info('Started queued RA %s for %s', item['kind'], item['system_name'])
        remove_queued_job(item['row_id'])
        return self._public(item)

    def _watch(self):
        while True:
            time.sleep(POLL_SECONDS)
            try:
                self.start_next()
            except Exception:
                logger.exception('RA queue could not start the next job')
            with self._lock:
                if not self._items:
                    self._thread = None
                    return

    def _public(self, item):
        return {
            'id': item['id'], 'kind': item['kind'], 'system_id': item['system_id'],
            'system_name': item['system_name'], 'user_id': item['user_id'],
            'position': self._items.index(item) + 1 if item in self._items else 0,
        }
