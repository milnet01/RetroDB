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
# Pass 42 — singleton factory keyed on the launcher_backend setting.  The
# singleton matters: LocalLauncher's in-memory ProcessRegistry must persist
# across requests so /api/launches/active returns rows that were registered
# by an earlier /api/game/<id>/launch call.
# =============================================================================

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
        backend = get_setting('launcher_backend', 'local')
        if backend == 'local':
            _singleton = LocalLauncher()
        elif backend == 'remote':
            raise NotImplementedError(
                "remote launcher backend is spec §F5; not implemented in v1"
            )
        else:
            raise ValueError(f"unknown launcher_backend: {backend!r}")
        return _singleton
