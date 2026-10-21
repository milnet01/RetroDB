# Pass 44 — LocalLauncher: real subprocess wiring.
import shutil
from pathlib import Path

import pytest


SLEEP = shutil.which('sleep')
TRUE = shutil.which('true')
FALSE = shutil.which('false')


# Generous: wait() returns the moment the child exits, so this bound costs
# nothing on the happy path and only matters for a genuinely stuck child.
_WAIT_S = 10.0


@pytest.fixture
def local_launcher():
    """A fresh LocalLauncher that kills every child still running at
    teardown, so a failing test cannot leak a `sleep 60` into later tests."""
    from services.launcher.local import LocalLauncher

    launcher = LocalLauncher()
    yield launcher
    for handle in launcher.active():
        try:
            launcher.kill(handle.token, timeout_s=2.0)
        except Exception:
            pass


@pytest.mark.skipif(not SLEEP, reason='no /bin/sleep')
def test_launch_then_kill_terminates_process(local_launcher):
    """`kill` with a 2s timeout must terminate a `sleep 60` child cleanly
    (POSIX SIGTERM → SIGKILL escalation in LocalLauncher.kill)."""
    from services.launcher.base import LaunchContext

    launcher = local_launcher
    ctx = LaunchContext(game_id=1, emulator_id=1, binary=Path(SLEEP),
                        argv=[SLEEP, '60'], token='t1')
    h = launcher.launch(ctx)
    assert h.pid > 0
    assert launcher.status('t1').state == 'running'

    end = launcher.kill('t1', timeout_s=2.0)
    assert end.state == 'exited'
    assert end.exit_code is not None


@pytest.mark.skipif(not TRUE, reason='no /bin/true')
def test_launch_quick_exit_reaps_cleanly(local_launcher):
    """A fast-exiting child (`/bin/true`) is reaped and surfaces exit_code=0."""
    from services.launcher.base import LaunchContext

    launcher = local_launcher
    ctx = LaunchContext(game_id=2, emulator_id=2, binary=Path(TRUE),
                        argv=[TRUE], token='t2')
    launcher.launch(ctx)
    launcher.wait('t2', timeout_s=_WAIT_S)
    # Status is read through status(), the public path the app uses.
    st = launcher.status('t2')
    assert st.state == 'exited'
    assert st.exit_code == 0


@pytest.mark.skipif(not FALSE, reason='no /bin/false')
def test_launch_failed_exit_code_propagates(local_launcher):
    """A failing child (`/bin/false`) surfaces its non-zero exit_code."""
    from services.launcher.base import LaunchContext

    launcher = local_launcher
    ctx = LaunchContext(game_id=3, emulator_id=3, binary=Path(FALSE),
                        argv=[FALSE], token='t3')
    launcher.launch(ctx)
    launcher.wait('t3', timeout_s=_WAIT_S)
    st = launcher.status('t3')
    assert st.state == 'exited'
    assert st.exit_code == 1


def test_status_unknown_token_raises(local_launcher):
    from services.launcher.base import LauncherError
    launcher = local_launcher
    # Pin the exact error wording — a refactor that raises LauncherError with a
    # generic message (e.g. "internal error") should fail this test loudly
    # rather than pass silently. Production message is "unknown token: <token>".
    with pytest.raises(LauncherError, match=r"unknown token.*does-not-exist"):
        launcher.status('does-not-exist')


@pytest.mark.skipif(not SLEEP, reason='no /bin/sleep')
def test_active_returns_running_only(local_launcher):
    """`active()` only includes still-running tokens; killed entries drop out."""
    from services.launcher.base import LaunchContext
    launcher = local_launcher
    ctx = LaunchContext(game_id=1, emulator_id=1, binary=Path(SLEEP),
                        argv=[SLEEP, '30'], token='running1')
    launcher.launch(ctx)
    assert any(h.token == 'running1' for h in launcher.active())
    launcher.kill('running1', timeout_s=2.0)
    assert all(h.token != 'running1' for h in launcher.active())


@pytest.mark.skipif(not TRUE, reason='no /bin/true')
def test_kill_idempotent_on_already_exited(local_launcher):
    """Calling `kill` on a token whose child has already exited is a no-op
    that returns an 'exited' status rather than raising."""
    from services.launcher.base import LaunchContext
    launcher = local_launcher
    ctx = LaunchContext(game_id=1, emulator_id=1, binary=Path(TRUE),
                        argv=[TRUE], token='quick')
    launcher.launch(ctx)
    assert launcher.wait('quick', timeout_s=_WAIT_S).state == 'exited'
    end = launcher.kill('quick', timeout_s=1.0)
    assert end.state == 'exited'


def test_wait_unknown_token_raises(local_launcher):
    from services.launcher.base import LauncherError
    with pytest.raises(LauncherError, match=r"unknown token.*nope"):
        local_launcher.wait('nope', timeout_s=1.0)


@pytest.mark.skipif(not SLEEP, reason='no /bin/sleep')
def test_wait_times_out_on_running_child(local_launcher):
    """wait() is bounded: a still-running child raises TimeoutExpired
    rather than blocking forever. The fixture kills the child afterwards."""
    import subprocess
    from services.launcher.base import LaunchContext
    ctx = LaunchContext(game_id=4, emulator_id=4, binary=Path(SLEEP),
                        argv=[SLEEP, '60'], token='slow')
    local_launcher.launch(ctx)
    with pytest.raises(subprocess.TimeoutExpired):
        local_launcher.wait('slow', timeout_s=0.05)
    assert local_launcher.status('slow').state == 'running'


def test_inv15_sigterm_sent_at_most_once(local_launcher, tmp_path):
    """PASS-59-64 INV-15: a second kill() during the first one's grace
    sends no second SIGTERM; it waits out the grace, then SIGKILL."""
    import sys
    import threading
    import time
    from services.launcher.base import LaunchContext

    hits, ready = tmp_path / 'hits', tmp_path / 'ready'
    child = (
        "import signal, sys, time, pathlib\n"
        "hits = pathlib.Path(sys.argv[1])\n"
        "signal.signal(signal.SIGTERM,"
        " lambda *a: hits.open('a').write('TERM\\n'))\n"
        "pathlib.Path(sys.argv[2]).touch()\n"
        "while True: time.sleep(0.05)\n"
    )
    ctx = LaunchContext(game_id=1, emulator_id=1, binary=Path(sys.executable),
                        argv=[sys.executable, '-c', child, str(hits), str(ready)],
                        env=None, cwd=None, token='inv15')
    local_launcher.launch(ctx)
    deadline = time.time() + _WAIT_S
    while not ready.exists() and time.time() < deadline:
        time.sleep(0.05)
    assert ready.exists(), 'stub child never installed its handler'

    first = threading.Thread(
        target=local_launcher.kill, args=('inv15',), kwargs={'timeout_s': 2.0})
    first.start()
    time.sleep(0.5)                      # inside the first call's grace
    status = local_launcher.kill('inv15', timeout_s=2.0)
    first.join(timeout=_WAIT_S)

    assert status.state == 'exited'
    assert hits.read_text().splitlines() == ['TERM']


class _UnkillableProc:
    """A child that survives SIGTERM and SIGKILL, as one stuck in the kernel
    can."""
    pid = 4242
    stderr = None

    def poll(self):
        return None

    def send_signal(self, sig):
        pass

    def kill(self):
        pass

    def wait(self, timeout=None):
        import subprocess
        raise subprocess.TimeoutExpired('stuck', timeout)


def test_kill_does_not_mark_a_surviving_child_exited(local_launcher):
    """A child still alive after SIGKILL stays running, so the registry
    neither reports it exited nor clears it out while it runs."""
    launcher = local_launcher
    launcher._registry.register(token='stuck', proc=_UnkillableProc(),
                                game_id=9, emulator_id=9, started_at=0.0)
    st = launcher.kill('stuck', timeout_s=0.1)
    assert st.state == 'running'
    assert launcher._registry.get('stuck').exit_time is None
    launcher._registry._entries.pop('stuck')  # the fixture cannot kill it


def test_quick_exit_status_carries_stderr(local_launcher, monkeypatch):
    """The first status read after a quick exit carries the error text, even
    when the stderr reader finishes a moment after the process."""
    import sys
    import time
    from services.launcher.base import LaunchContext
    from services.launcher.local import LocalLauncher

    original = LocalLauncher._drain_stderr

    def slow_drain(self, token, proc):
        time.sleep(0.3)
        original(self, token, proc)

    monkeypatch.setattr(LocalLauncher, '_drain_stderr', slow_drain)
    launcher = local_launcher
    ctx = LaunchContext(game_id=5, emulator_id=5, binary=Path(sys.executable),
                        argv=[sys.executable, '-c',
                              'import sys; sys.stderr.write("core missing"); sys.exit(2)'],
                        token='err')
    launcher.launch(ctx)
    launcher.wait('err', timeout_s=_WAIT_S)
    st = launcher.status('err')
    assert st.state == 'exited'
    assert 'core missing' in st.stderr_tail
