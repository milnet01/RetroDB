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
# get_launcher() — task 9 wires the factory.
# =============================================================================

from services.launcher.base import (
    Launcher, LaunchContext, LaunchHandle, LaunchStatus,
    LauncherError, BinaryNotFoundError, LaunchResolutionError,
)
