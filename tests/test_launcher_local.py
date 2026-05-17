# Pass 44 — LocalLauncher: real subprocess wiring.
import shutil
import time
from pathlib import Path

import pytest


SLEEP = shutil.which('sleep')
TRUE = shutil.which('true')
FALSE = shutil.which('false')


def _poll_exited(launcher, token, deadline_s=2.0):
    """Poll launcher.status(token) until state == 'exited' or deadline passes.

    Returns the final status. Fails the test loudly with the last-observed
    status if the deadline is breached — replaces the prior pattern of a
    bare poll loop whose timeout surfaced as a silent downstream assert.
    """
    deadline = time.time() + deadline_s
    st = None
    while time.time() < deadline:
        st = launcher.status(token)
        if st.state == 'exited':
            return st
        time.sleep(0.05)
    pytest.fail(f"timed out waiting for state; last={st!r}")


@pytest.mark.skipif(not SLEEP, reason='no /bin/sleep')
def test_launch_then_kill_terminates_process():
    """`kill` with a 2s timeout must terminate a `sleep 60` child cleanly
    (POSIX SIGTERM → SIGKILL escalation in LocalLauncher.kill)."""
    from services.launcher.local import LocalLauncher
    from services.launcher.base import LaunchContext

    launcher = LocalLauncher()
    ctx = LaunchContext(game_id=1, emulator_id=1, binary=Path(SLEEP),
                        argv=[SLEEP, '60'], token='t1')
    h = launcher.launch(ctx)
    assert h.pid > 0
    assert launcher.status('t1').state == 'running'

    end = launcher.kill('t1', timeout_s=2.0)
    assert end.state == 'exited'
    assert end.exit_code is not None


@pytest.mark.skipif(not TRUE, reason='no /bin/true')
def test_launch_quick_exit_reaps_cleanly():
    """A fast-exiting child (`/bin/true`) is reaped and surfaces exit_code=0."""
    from services.launcher.local import LocalLauncher
    from services.launcher.base import LaunchContext

    launcher = LocalLauncher()
    ctx = LaunchContext(game_id=2, emulator_id=2, binary=Path(TRUE),
                        argv=[TRUE], token='t2')
    launcher.launch(ctx)
    st = _poll_exited(launcher, 't2')
    assert st is not None, "poll loop never set st"
    assert st.state == 'exited'
    assert st.exit_code == 0


@pytest.mark.skipif(not FALSE, reason='no /bin/false')
def test_launch_failed_exit_code_propagates():
    """A failing child (`/bin/false`) surfaces its non-zero exit_code."""
    from services.launcher.local import LocalLauncher
    from services.launcher.base import LaunchContext

    launcher = LocalLauncher()
    ctx = LaunchContext(game_id=3, emulator_id=3, binary=Path(FALSE),
                        argv=[FALSE], token='t3')
    launcher.launch(ctx)
    st = _poll_exited(launcher, 't3')
    assert st is not None, "poll loop never set st"
    assert st.exit_code == 1


def test_status_unknown_token_raises():
    from services.launcher.local import LocalLauncher
    from services.launcher.base import LauncherError
    launcher = LocalLauncher()
    with pytest.raises(LauncherError):
        launcher.status('does-not-exist')


@pytest.mark.skipif(not SLEEP, reason='no /bin/sleep')
def test_active_returns_running_only():
    """`active()` only includes still-running tokens; killed entries drop out."""
    from services.launcher.local import LocalLauncher
    from services.launcher.base import LaunchContext
    launcher = LocalLauncher()
    ctx = LaunchContext(game_id=1, emulator_id=1, binary=Path(SLEEP),
                        argv=[SLEEP, '30'], token='running1')
    launcher.launch(ctx)
    assert any(h.token == 'running1' for h in launcher.active())
    launcher.kill('running1', timeout_s=2.0)
    assert all(h.token != 'running1' for h in launcher.active())


@pytest.mark.skipif(not TRUE, reason='no /bin/true')
def test_kill_idempotent_on_already_exited():
    """Calling `kill` on a token whose child has already exited is a no-op
    that returns an 'exited' status rather than raising."""
    from services.launcher.local import LocalLauncher
    from services.launcher.base import LaunchContext
    launcher = LocalLauncher()
    ctx = LaunchContext(game_id=1, emulator_id=1, binary=Path(TRUE),
                        argv=[TRUE], token='quick')
    launcher.launch(ctx)
    _poll_exited(launcher, 'quick')
    end = launcher.kill('quick', timeout_s=1.0)
    assert end.state == 'exited'
