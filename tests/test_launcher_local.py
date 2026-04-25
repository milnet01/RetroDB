# Pass 44 — LocalLauncher: real subprocess wiring.
import shutil
import time
from pathlib import Path

import pytest


SLEEP = shutil.which('sleep')
TRUE = shutil.which('true')
FALSE = shutil.which('false')


@pytest.mark.skipif(not SLEEP, reason='no /bin/sleep')
def test_launch_then_kill_terminates_process():
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
    from services.launcher.local import LocalLauncher
    from services.launcher.base import LaunchContext

    launcher = LocalLauncher()
    ctx = LaunchContext(game_id=2, emulator_id=2, binary=Path(TRUE),
                        argv=[TRUE], token='t2')
    launcher.launch(ctx)
    deadline = time.time() + 2.0
    st = None
    while time.time() < deadline:
        st = launcher.status('t2')
        if st.state == 'exited':
            break
        time.sleep(0.05)
    assert st is not None and st.state == 'exited'
    assert st.exit_code == 0


@pytest.mark.skipif(not FALSE, reason='no /bin/false')
def test_launch_failed_exit_code_propagates():
    from services.launcher.local import LocalLauncher
    from services.launcher.base import LaunchContext

    launcher = LocalLauncher()
    ctx = LaunchContext(game_id=3, emulator_id=3, binary=Path(FALSE),
                        argv=[FALSE], token='t3')
    launcher.launch(ctx)
    deadline = time.time() + 2.0
    st = None
    while time.time() < deadline:
        st = launcher.status('t3')
        if st.state == 'exited':
            break
        time.sleep(0.05)
    assert st is not None and st.exit_code == 1


def test_status_unknown_token_raises():
    from services.launcher.local import LocalLauncher
    from services.launcher.base import LauncherError
    launcher = LocalLauncher()
    with pytest.raises(LauncherError):
        launcher.status('does-not-exist')


@pytest.mark.skipif(not SLEEP, reason='no /bin/sleep')
def test_active_returns_running_only():
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
    from services.launcher.local import LocalLauncher
    from services.launcher.base import LaunchContext
    launcher = LocalLauncher()
    ctx = LaunchContext(game_id=1, emulator_id=1, binary=Path(TRUE),
                        argv=[TRUE], token='quick')
    launcher.launch(ctx)
    deadline = time.time() + 2.0
    while time.time() < deadline and launcher.status('quick').state == 'running':
        time.sleep(0.05)
    end = launcher.kill('quick', timeout_s=1.0)
    assert end.state == 'exited'
