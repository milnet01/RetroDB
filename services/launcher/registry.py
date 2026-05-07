# =============================================================================
# RETRODB - Launcher process registry
# =============================================================================
# In-memory, thread-safe map of {token: ProcessEntry}. Used by LocalLauncher
# to track active subprocesses and to expose them to /api/launches/active.
#
# Entries linger `post_exit_ttl_s` seconds after exit so the UI can surface
# "exited 30s ago, exit code 1" before the entry GCs. Default 3600s (1h).
#
# v1 is process-scoped; multi-worker deployments need a DB-backed registry
# (see spec §Future work F1).
# =============================================================================

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from services.launcher.base import LaunchHandle


@dataclass
class ProcessEntry:
    handle: LaunchHandle
    proc: object                 # subprocess.Popen — typed as object to avoid
                                 # importing subprocess just for an annotation
    exit_time: Optional[float] = None
    stderr_tail: str = ''        # populated by LocalLauncher on reap


class ProcessRegistry:
    def __init__(self, post_exit_ttl_s: float = 3600.0):
        self._lock = threading.Lock()
        self._entries: dict[str, ProcessEntry] = {}
        self._ttl = post_exit_ttl_s

    def register(self, *, token: str, proc, game_id: int, emulator_id: int,
                 started_at: float) -> LaunchHandle:
        h = LaunchHandle(token=token, pid=proc.pid, game_id=game_id,
                         emulator_id=emulator_id, started_at=started_at)
        with self._lock:
            self._entries[token] = ProcessEntry(handle=h, proc=proc)
        return h

    def get(self, token: str) -> Optional[ProcessEntry]:
        with self._lock:
            return self._entries.get(token)

    def active(self) -> list[LaunchHandle]:
        """Return handles for entries whose proc.poll() is None (still running)."""
        with self._lock:
            return [e.handle for e in self._entries.values() if e.proc.poll() is None]

    def find_running_by_game(self, game_id: int) -> Optional[LaunchHandle]:
        """First running entry whose game_id matches, or None."""
        with self._lock:
            for entry in self._entries.values():
                if entry.handle.game_id == game_id and entry.proc.poll() is None:
                    return entry.handle
        return None

    def _mark_exited(self, token: str, *, exit_time: float):
        with self._lock:
            entry = self._entries.get(token)
            if entry is not None and entry.exit_time is None:
                entry.exit_time = exit_time

    def gc(self) -> None:
        """Remove entries that exited more than ttl seconds ago."""
        cutoff = time.time() - self._ttl
        with self._lock:
            doomed = [t for t, e in self._entries.items()
                      if e.exit_time is not None and e.exit_time < cutoff]
            for t in doomed:
                del self._entries[t]

    def remove(self, token: str) -> None:
        with self._lock:
            self._entries.pop(token, None)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)
