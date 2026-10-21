# =============================================================================
# RETRODB - Launcher package
# =============================================================================
# Public API:
#   from services.launcher import (
#       get_launcher,
#       Launcher, LaunchContext, LaunchHandle, LaunchStatus,
#       LauncherError, BinaryNotFoundError, LaunchResolutionError,
#   )
#
# Pass 44 — singleton factory keyed on the launcher_backend setting.  The
# singleton matters: LocalLauncher's in-memory ProcessRegistry must persist
# across requests so /api/launches/active returns rows that were registered
# by an earlier /api/game/<id>/launch call.
# =============================================================================

import logging
from threading import Lock
from typing import Optional

from settings_manager import get_setting

from services.launcher.base import (
    Launcher, LaunchContext, LaunchHandle, LaunchStatus,
    LauncherError, BinaryNotFoundError, LaunchResolutionError,
)
from services.launcher.local import LocalLauncher

__all__ = [
    'get_launcher',
    'Launcher', 'LaunchContext', 'LaunchHandle', 'LaunchStatus',
    'LauncherError', 'BinaryNotFoundError', 'LaunchResolutionError',
]


logger = logging.getLogger(__name__)
_singleton_lock = Lock()
_singleton: Optional[Launcher] = None


def get_launcher() -> Launcher:
    """Return the configured Launcher impl.  Singleton — the registry must
    persist across requests."""
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is not None:
            return _singleton
        # get_setting does not validate on read, so a value saved before
        # 'remote' left the allowlist still arrives here (PASS-59-64 §4.3).
        backend = get_setting('launcher_backend', 'local')
        if backend != 'local':
            logger.warning("launcher_backend %r is not supported; "
                           "launching locally", backend)
        _singleton = LocalLauncher()
        return _singleton
