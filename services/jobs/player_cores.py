# =============================================================================
# RETRODB - The player's core installs (PASS-59-81 §4.4–4.5)
# =============================================================================
# One background job downloads every core the player is asked for: by Play,
# when a game's core is missing, or by Settings > Emulators. A request for a
# core already queued joins it. After each install for a system, the player's
# system row and the system's cfg are written (player_cores.map_system).
#
# Not persisted for resume: a restart loses a download, and the next Play or
# button press asks again.
# =============================================================================

import logging
import threading
import time

from services.jobs.base import acquire_job_singleton_lock, release_singleton_fd

logger = logging.getLogger(__name__)

SHADERS = '_shaders'   # the queue's name for the shader pack
RETROARCH = '_retroarch'   # ...and for RetroArch itself (PASS-59-139)


class PlayerCoresJob:
    """Installs queued cores, one at a time, on one thread."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.job_id = None
        self.running = False
        self.queue = []          # [(core, system_id or None, force)]
        self.current_item = ''
        self.done = []
        self.errors = {}         # {core: message}
        self.app = None

    def get_status(self):
        with self._lock:
            total = len(self.done) + len(self.errors) + len(self.queue) + bool(self.current_item)
            processed = len(self.done) + len(self.errors)
            return {
                'job_id': self.job_id,
                'running': self.running,
                'completed': not self.running and self.job_id is not None,
                'current_item': self.current_item,
                'queued': [c for c, _s, _f in self.queue],
                'processed': processed,
                'total': total,
                'percent': int(processed / total * 100) if total else 0,
                'success': list(self.done),
                'failed': len(self.errors),
                'errors': dict(self.errors),
            }

    def request(self, items, force=False):
        """Queue [(core, system_id or None)] and start the worker if idle.
        Returns the job id the caller can poll."""
        from flask import current_app
        with self._lock:
            if not self.running:
                self.job_id = f"player_cores_{int(time.time() * 1000)}"
                self.done, self.errors, self.queue = [], {}, []
            for core, system_id in items:
                self.errors.pop(core, None)
                if not any(c == core and s == system_id for c, s, _f in self.queue):
                    self.queue.append((core, system_id, force))
            if self.running:
                return self.job_id
            self.running = True
            self.app = current_app._get_current_object()
        self._thread = threading.Thread(target=self._worker, name='player-cores', daemon=True)
        self._thread.start()
        return self.job_id

    def _next(self):
        with self._lock:
            if not self.queue:
                self.current_item = ''
                return None
            item = self.queue.pop(0)
            self.current_item = item[0]
            return item

    def _worker(self):
        from services import player_cores
        fd = acquire_job_singleton_lock('player_cores')
        if fd is None:
            with self._lock:
                for core, _s, _f in self.queue:
                    self.errors[core] = 'Core downloads are already running in another process.'
                self.queue, self.running, self.current_item = [], False, ''
            return
        self._singleton_fd = fd
        try:
            with self.app.app_context():
                while True:
                    item = self._next()
                    if item is None:
                        break
                    core, system_id, force = item
                    try:
                        if core == SHADERS:
                            if force or not player_cores.shaders_ready():
                                player_cores.install_shaders()
                        elif core == RETROARCH:
                            from services import player_install
                            player_install.install()
                        else:
                            if force or not player_cores.is_installed(core):
                                player_cores.install(core)
                            if system_id is not None:
                                player_cores.map_system(system_id, core)
                                self._shaders_for(player_cores, system_id)
                        with self._lock:
                            self.done.append(core)
                    except Exception as e:  # noqa: BLE001 — one core's failure ends only that core
                        logger.warning("player core %s not installed: %s", core, e)
                        with self._lock:
                            self.errors[core] = str(e)
        finally:
            with self._lock:
                self.running, self.current_item = False, ''
            release_singleton_fd(self)

    def _shaders_for(self, player_cores, system_id):
        """The first install for a system whose chosen shader is not `none`
        also fetches the shader pack (§4.5)."""
        row = player_cores.player_row()
        folder = player_cores.query("SELECT folder FROM systems WHERE id = ?",
                                    (system_id,), one=True)
        if row and folder and player_cores.needs_shaders(folder['folder'], system_id,
                                                         None, row['id']):
            with self._lock:
                if not any(c == SHADERS for c, _s, _f in self.queue):
                    self.queue.append((SHADERS, None, False))
