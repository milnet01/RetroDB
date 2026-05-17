# Pass 44 — Launcher Protocol + dataclasses shape pin.
from pathlib import Path

import pytest

from services.launcher.base import (
    BinaryNotFoundError,
    LaunchContext,
    LaunchHandle,
    LaunchResolutionError,
    LaunchStatus,
    Launcher,
    LauncherError,
)


class TestLaunchContext:
    """Pin the LaunchContext dataclass field names, types, and optional
    fields — keeps the resolver → runner contract from drifting silently."""

    def test_construct_minimal(self):
        ctx = LaunchContext(
            game_id=1, emulator_id=1,
            binary=Path('/usr/bin/retroarch'),
            argv=['/usr/bin/retroarch', '-L', 'core.so', '/roms/g.bin'],
            token='abc',
        )
        assert ctx.game_id == 1
        # Exact match — guards against argv[0] being a wrapper script with a
        # name that merely ends in 'retroarch' (ASSERT-2).
        assert ctx.argv[0] == '/usr/bin/retroarch'

    def test_optional_cwd_env(self):
        ctx = LaunchContext(
            game_id=1, emulator_id=1,
            binary=Path('/usr/bin/x'),
            argv=['/usr/bin/x'], token='t',
            cwd=Path('/tmp'), env={'FOO': 'bar'},
        )
        assert ctx.cwd == Path('/tmp')
        assert ctx.env == {'FOO': 'bar'}


class TestLaunchHandle:
    """Pin the LaunchHandle dataclass — frozen instance returned by Launcher.launch."""

    def test_construct(self):
        h = LaunchHandle(token='t', pid=42, game_id=1, emulator_id=2, started_at=100.0)
        assert h.pid == 42

    def test_frozen(self):
        h = LaunchHandle(token='t', pid=42, game_id=1, emulator_id=2, started_at=100.0)
        with pytest.raises((AttributeError, TypeError)):
            h.pid = 99


class TestLaunchStatus:
    """Pin the LaunchStatus state literal + exit_code/runtime_s shape."""

    def test_running_state(self):
        s = LaunchStatus(state='running', exit_code=None, runtime_s=2.5)
        assert s.state == 'running'
        assert s.exit_code is None

    def test_exited_state(self):
        s = LaunchStatus(state='exited', exit_code=0, runtime_s=120.0)
        assert s.state == 'exited'
        assert s.exit_code == 0


class TestExceptions:
    """Pin the launcher exception hierarchy so callers can catch by base."""

    def test_resolution_error_inherits_launcher_error(self):
        assert issubclass(LaunchResolutionError, LauncherError)

    def test_binary_not_found_inherits_launcher_error(self):
        assert issubclass(BinaryNotFoundError, LauncherError)


class TestLauncherProtocol:
    """Pin the structural Protocol — `launch`, `status`, `kill`, `active` must
    all be callable attributes on the class, not e.g. accidentally replaced
    by data attributes after a refactor."""

    @pytest.mark.parametrize("method", ['launch', 'status', 'kill', 'active'])
    def test_protocol_method_is_callable(self, method):
        # callable() check distinguishes 'method renamed to wrong case' or
        # 'method replaced by a data attribute' from the correct shape, where
        # plain hasattr would pass either failure mode (ACC-3). Parametrized
        # so a regression that deletes 3 of 4 methods reports 3 failures
        # instead of stopping at the first.
        attr = getattr(Launcher, method, None)
        assert callable(attr), f"Launcher.{method} is not callable: {attr!r}"
