# =============================================================================
# RETRODB - LocalLauncher: subprocess.Popen impl
# =============================================================================
# Launches emulator processes on the same host as the Flask worker. Always
# shell=False; argv comes from the resolver pre-shell-quoted.
#
# Lifecycle:
#   launch()  -> Popen, register handle
#   status()  -> proc.poll(); transition to 'exited' on first non-None
#   kill()    -> SIGTERM, poll up to timeout_s, then SIGKILL
#
# stderr is drained into a 4KB ring buffer (last bytes wins) so a quickly-
# exiting emulator's failure can be surfaced to the user.
# =============================================================================

from __future__ import annotations

import logging
import signal
import subprocess
import threading
import time
from typing import Optional

from services.launcher.base import (
    LaunchContext, LaunchHandle, LaunchStatus, LauncherError,
)
from services.launcher.registry import ProcessEntry, ProcessRegistry

logger = logging.getLogger(__name__)


_STDERR_TAIL_BYTES = 4096


class LocalLauncher:
    def __init__(self, registry: Optional[ProcessRegistry] = None):
        self._registry = registry or ProcessRegistry()

    # ---------------- Launcher protocol --------------------------------------

    def launch(self, ctx: LaunchContext) -> LaunchHandle:
        try:
            proc = subprocess.Popen(
                ctx.argv,
                cwd=str(ctx.cwd) if ctx.cwd else None,
                env=ctx.env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                close_fds=True,
            )
        except OSError as e:
            raise LauncherError(f"failed to spawn {ctx.argv[0]}: {e}") from e

        handle = self._registry.register(
            token=ctx.token, proc=proc,
            game_id=ctx.game_id, emulator_id=ctx.emulator_id,
            started_at=time.time(),
        )
        threading.Thread(target=self._drain_stderr, args=(ctx.token, proc),
                         daemon=True).start()

        logger.info("launched game=%s emulator=%s pid=%s argv=%s",
                    ctx.game_id, ctx.emulator_id, proc.pid, ctx.argv)
        return handle

    def status(self, token: str) -> LaunchStatus:
        entry = self._registry.get(token)
        if entry is None:
            raise LauncherError(f"unknown token: {token}")
        return self._status_from_entry(entry)

    def kill(self, token: str, *, timeout_s: float = 5.0) -> LaunchStatus:
        entry = self._registry.get(token)
        if entry is None:
            raise LauncherError(f"unknown token: {token}")
        proc = entry.proc

        if proc.poll() is None:
            try:
                proc.send_signal(signal.SIGTERM)
            except OSError:
                pass
            deadline = time.time() + timeout_s
            while time.time() < deadline and proc.poll() is None:
                time.sleep(0.1)
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
                try:
                    proc.wait(timeout=2.0)
                except subprocess.TimeoutExpired:
                    pass

        if entry.exit_time is None:
            self._registry._mark_exited(token, exit_time=time.time())
        return self._status_from_entry(entry)

    def active(self) -> list[LaunchHandle]:
        return self._registry.active()

    # ---------------- internals ---------------------------------------------

    def _status_from_entry(self, entry: ProcessEntry) -> LaunchStatus:
        rc = entry.proc.poll()
        runtime = time.time() - entry.handle.started_at
        if rc is None:
            return LaunchStatus(state='running', exit_code=None, runtime_s=runtime)
        if entry.exit_time is None:
            self._registry._mark_exited(entry.handle.token, exit_time=time.time())
        if entry.exit_time:
            runtime = entry.exit_time - entry.handle.started_at
        return LaunchStatus(state='exited', exit_code=rc, runtime_s=runtime,
                            stderr_tail=entry.stderr_tail)

    def _drain_stderr(self, token: str, proc):
        """Background thread: read stderr in chunks, retain last 4KB."""
        try:
            tail = b''
            while True:
                chunk = proc.stderr.read(1024) if proc.stderr else b''
                if not chunk:
                    break
                tail = (tail + chunk)[-_STDERR_TAIL_BYTES:]
            entry = self._registry.get(token)
            if entry is not None:
                entry.stderr_tail = tail.decode('utf-8', errors='replace')
        except Exception as e:
            logger.warning("stderr drain failed for %s: %s", token, e)
