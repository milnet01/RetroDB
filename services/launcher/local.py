# =============================================================================
# RETRODB - LocalLauncher: subprocess.Popen impl
# =============================================================================
# Launches emulator processes on the same host as the Flask worker. Always
# shell=False; argv comes from the resolver as literal, already-split words
# (no shell quoting), so pass it to Popen unchanged.
#
# Lifecycle:
#   launch()  -> Popen, register handle
#   status()  -> proc.poll(); transition to 'exited' on first non-None
#   kill()    -> SIGTERM (once per process), poll up to timeout_s, then SIGKILL;
#                a player with a quit_port gets a network QUIT instead (§4.6)
#   exit      -> the call that first marks an entry exited runs its on_exit
#   wait()    -> block until the child exits; raises TimeoutExpired after timeout_s
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
from services.retroarch_command import send_quit

logger = logging.getLogger(__name__)


_STDERR_TAIL_BYTES = 4096
_DRAIN_JOIN_S = 0.5


class LocalLauncher:
    def __init__(self, registry: Optional[ProcessRegistry] = None):
        # `is None`, not `or`: an empty registry has len 0 and is falsy.
        self._registry = registry if registry is not None else ProcessRegistry()
        self._term_lock = threading.Lock()

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
        drain = threading.Thread(target=self._drain_stderr, args=(ctx.token, proc),
                                 daemon=True)
        entry = self._registry.get(ctx.token)
        entry.drain = drain
        entry.on_exit = ctx.on_exit
        entry.quit_port = ctx.quit_port
        drain.start()

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
            # SIGTERM at most once per process (PASS-59-64 INV-15): a repeat
            # request only waits out the first one's grace, then escalates.
            with self._term_lock:
                first = entry.term_sent_at is None
                if first:
                    entry.term_sent_at = time.time()
                    self._ask_to_quit(entry)
            deadline = entry.term_sent_at + timeout_s
            resend_at = entry.term_sent_at + 1.0
            while time.time() < deadline and proc.poll() is None:
                # The player drops a QUIT that lands as its menu opens or
                # closes, so a still-running one gets one more (§4.6).
                if first and entry.quit_port and resend_at and time.time() >= resend_at:
                    resend_at = None
                    send_quit(entry.quit_port)
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

        # A child that outlived SIGKILL (stuck in the kernel) is still
        # running; marking it exited would let gc() drop it while it runs.
        if entry.exit_time is None and proc.poll() is not None:
            self._mark_exited(entry, time.time())
        return self._status_from_entry(entry)

    def wait(self, token: str, *, timeout_s: Optional[float] = None) -> LaunchStatus:
        """Block until the child exits, then return its status.

        Raises subprocess.TimeoutExpired if it is still running after
        timeout_s seconds. Not part of the Launcher protocol: callers that
        hold a LocalLauncher (tests, chiefly) use it to join a child
        instead of polling status()."""
        entry = self._registry.get(token)
        if entry is None:
            raise LauncherError(f"unknown token: {token}")
        entry.proc.wait(timeout=timeout_s)
        return self._status_from_entry(entry)

    def active(self) -> list[LaunchHandle]:
        # Mark every ended process exited, then collect the ones past their
        # TTL, so the registry stays bounded (PASS-59-64 §4.3).
        now = time.time()
        for token in self._registry.newly_exited():
            entry = self._registry.get(token)
            if entry is not None:
                self._mark_exited(entry, now)
        self._registry.gc()
        return self._registry.active()

    # ---------------- internals ---------------------------------------------

    @staticmethod
    def _ask_to_quit(entry: ProcessEntry) -> None:
        """The first stop request: a network QUIT to a player that has a
        command port (macOS, Windows), else one SIGTERM."""
        if entry.quit_port:
            send_quit(entry.quit_port)
            return
        try:
            entry.proc.send_signal(signal.SIGTERM)
        except OSError:
            pass

    def _mark_exited(self, entry: ProcessEntry, exit_time: float) -> None:
        """Mark an entry exited; the one call that does runs its on_exit,
        synchronously, so it has finished before the next launch resolves
        (PASS-59-64 §4.5). A failing hook is logged, never raised."""
        if not self._registry.mark_exited(entry.handle.token, exit_time=exit_time):
            return
        if entry.on_exit is not None:
            try:
                entry.on_exit()
            except Exception:
                logger.exception("post-exit hook failed for %s", entry.handle.token)

    def _status_from_entry(self, entry: ProcessEntry) -> LaunchStatus:
        rc = entry.proc.poll()
        runtime = time.time() - entry.handle.started_at
        if rc is None:
            return LaunchStatus(state='running', exit_code=None, runtime_s=runtime)
        # The reader may still be on the last of stderr when the process is
        # already gone; give it a moment so the first status read carries
        # the error text. Bounded, because a grandchild that inherited
        # stderr keeps the pipe open past the child's exit.
        if entry.drain is not None:
            entry.drain.join(timeout=_DRAIN_JOIN_S)
        if entry.exit_time is None:
            self._mark_exited(entry, time.time())
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
