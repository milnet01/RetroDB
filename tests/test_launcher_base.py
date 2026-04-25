# Pass 42 — Launcher Protocol + dataclasses shape pin.
import pytest


class TestLaunchContext:
    def test_construct_minimal(self):
        from pathlib import Path
        from services.launcher.base import LaunchContext
        ctx = LaunchContext(
            game_id=1, emulator_id=1,
            binary=Path('/usr/bin/retroarch'),
            argv=['/usr/bin/retroarch', '-L', 'core.so', '/roms/g.bin'],
            token='abc',
        )
        assert ctx.game_id == 1
        assert ctx.argv[0].endswith('retroarch')

    def test_optional_cwd_env(self):
        from pathlib import Path
        from services.launcher.base import LaunchContext
        ctx = LaunchContext(
            game_id=1, emulator_id=1,
            binary=Path('/usr/bin/x'),
            argv=['/usr/bin/x'], token='t',
            cwd=Path('/tmp'), env={'FOO': 'bar'},
        )
        assert ctx.cwd == Path('/tmp')
        assert ctx.env == {'FOO': 'bar'}


class TestLaunchHandle:
    def test_construct(self):
        from services.launcher.base import LaunchHandle
        h = LaunchHandle(token='t', pid=42, game_id=1, emulator_id=2, started_at=100.0)
        assert h.pid == 42

    def test_frozen(self):
        from services.launcher.base import LaunchHandle
        h = LaunchHandle(token='t', pid=42, game_id=1, emulator_id=2, started_at=100.0)
        with pytest.raises((AttributeError, TypeError)):
            h.pid = 99


class TestLaunchStatus:
    def test_running_state(self):
        from services.launcher.base import LaunchStatus
        s = LaunchStatus(state='running', exit_code=None, runtime_s=2.5)
        assert s.state == 'running'
        assert s.exit_code is None

    def test_exited_state(self):
        from services.launcher.base import LaunchStatus
        s = LaunchStatus(state='exited', exit_code=0, runtime_s=120.0)
        assert s.state == 'exited'
        assert s.exit_code == 0


class TestExceptions:
    def test_resolution_error_inherits_launcher_error(self):
        from services.launcher.base import LaunchResolutionError, LauncherError
        assert issubclass(LaunchResolutionError, LauncherError)

    def test_binary_not_found_inherits_launcher_error(self):
        from services.launcher.base import BinaryNotFoundError, LauncherError
        assert issubclass(BinaryNotFoundError, LauncherError)


class TestLauncherProtocol:
    def test_protocol_methods(self):
        from services.launcher.base import Launcher
        assert hasattr(Launcher, 'launch')
        assert hasattr(Launcher, 'status')
        assert hasattr(Launcher, 'kill')
        assert hasattr(Launcher, 'active')
