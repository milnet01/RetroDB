# =============================================================================
# RETRODB - Launcher base types
# =============================================================================
# Protocol + dataclasses for the launcher subsystem. Implementations live in
# sibling modules: local.py (subprocess.Popen), and a future remote.py
# (HTTPS-to-agent). The factory in services/launcher/__init__.py picks one
# based on the launcher_backend setting.
# =============================================================================

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional, Protocol


# -----------------------------------------------------------------------------
# Exceptions
# -----------------------------------------------------------------------------

class LauncherError(Exception):
    """Base for all launcher-subsystem errors."""


class LaunchResolutionError(LauncherError):
    """Raised when game_id cannot be turned into a runnable LaunchContext.

    Causes: missing emulator mapping, missing core, missing binary,
    invalid template variable, ROM path outside scan roots.
    """


class BinaryNotFoundError(LauncherError):
    """Raised when the resolved binary doesn't exist on PATH and has no
    valid binary_path_override."""


# -----------------------------------------------------------------------------
# Dataclasses
# -----------------------------------------------------------------------------

@dataclass
class LaunchContext:
    """Fully-resolved launch parameters: a Launcher.launch() input."""
    game_id: int
    emulator_id: int
    binary: Path
    argv: list           # final shell-free argv list passed to subprocess
    token: str           # opaque caller-facing identifier (secrets.token_urlsafe)
    cwd: Optional[Path] = None
    env: Optional[dict] = None


@dataclass(frozen=True)
class LaunchHandle:
    """A reference to a running (or recently-exited) emulator process."""
    token: str
    pid: int
    game_id: int
    emulator_id: int
    started_at: float    # time.time() at Popen() return


@dataclass
class LaunchStatus:
    state: Literal['running', 'exited']
    exit_code: Optional[int]
    runtime_s: float
    stderr_tail: str = ''   # last 4KB on exit, '' while running


# -----------------------------------------------------------------------------
# Protocol
# -----------------------------------------------------------------------------

class Launcher(Protocol):
    """Backend-agnostic launcher interface. v1 ships LocalLauncher only."""

    def launch(self, ctx: LaunchContext) -> LaunchHandle: ...
    def status(self, token: str) -> LaunchStatus: ...
    def kill(self, token: str, *, timeout_s: float = 5.0) -> LaunchStatus: ...
    def active(self) -> list: ...   # list[LaunchHandle]
