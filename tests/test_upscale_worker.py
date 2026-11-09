"""PASS-59-269: the AI upscaler runs in a helper process.

The server side (`upscale_worker._Remote`) is driven against small fake
helpers that speak the same pickle protocol, so no model loads here.
"""
import pickle
import subprocess
import sys
import textwrap

import pytest

from services import upscale_worker

# A fake helper: answers each request by the action named in its argv.
_FAKE = textwrap.dedent('''
    import os, pickle, sys
    action = sys.argv[1]
    req = pickle.load(sys.stdin.buffer)
    if action == 'crash':
        os._exit(3)
    if action == 'idle':
        os._exit(0)
    reply = ('ok', req[1] * 2) if action == 'ok' else ('unavailable',)
    pickle.dump(reply, sys.stdout.buffer)
    sys.stdout.flush()
''')


def _remote(monkeypatch, *actions):
    """A _Remote whose helpers act out `actions` in turn, one per start."""
    remote = upscale_worker._Remote()
    plan = list(actions)
    started = []

    def _argv():
        started.append(remote.cpu_only)
        return [sys.executable, '-c', _FAKE, plan.pop(0)]
    monkeypatch.setattr(remote, '_argv', _argv)
    return remote, started


def test_an_upscale_comes_back_from_the_helper(monkeypatch):
    remote, _ = _remote(monkeypatch, 'ok')
    assert remote.enhance(21) == (42, None)


def test_a_helper_that_left_for_idleness_is_restarted_once(monkeypatch):
    remote, started = _remote(monkeypatch, 'idle', 'ok')
    assert remote.enhance(5) == (10, None)
    assert len(started) == 2 and not remote.cpu_only


def test_a_crash_moves_to_cpu_and_a_second_crash_turns_upscaling_off(monkeypatch):
    remote, started = _remote(monkeypatch, 'crash', 'crash')
    with pytest.raises(RuntimeError):
        remote.enhance(1)
    assert remote.cpu_only and not remote.disabled
    with pytest.raises(RuntimeError):
        remote.enhance(1)
    assert started == [False, True]
    assert remote.disabled
    assert remote.enhance(1) == (None, None)


def test_a_helper_with_no_upscaler_turns_upscaling_off(monkeypatch):
    remote, started = _remote(monkeypatch, 'unavailable')
    assert remote.enhance(1) == (None, None)
    assert remote.disabled
    assert remote.enhance(1) == (None, None) and len(started) == 1


def test_get_offers_no_upscaler_without_onnxruntime(monkeypatch):
    monkeypatch.setattr(upscale_worker, '_installed', False)
    assert upscale_worker.get() is None


def test_the_helper_answers_then_exits_when_idle(tmp_path):
    """The real child_main, with the model replaced: one reply, then a clean
    exit once IDLE_SECONDS pass with no work."""
    script = textwrap.dedent('''
        import sys
        from services import image_utils, upscale_worker
        upscale_worker.IDLE_SECONDS = 1
        upscale_worker._log_to_file = lambda: None
        image_utils._get_local_upscaler = lambda: object()
        image_utils._enhance_local = lambda arr: arr + 1
        upscale_worker.child_main([])
    ''')
    proc = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, cwd=upscale_worker.Path(
                                upscale_worker.__file__).resolve().parent.parent)
    pickle.dump(('enhance', 41), proc.stdin)
    proc.stdin.flush()
    assert pickle.load(proc.stdout) == ('ok', 42)
    assert proc.wait(timeout=10) == 0


def test_an_ended_helper_is_collected_without_waiting_for_the_next_upscale(monkeypatch):
    import time
    remote, _ = _remote(monkeypatch, 'ok')
    remote.enhance(1)      # the fake helper exits after one reply
    deadline = time.monotonic() + 5
    while remote._proc.returncode is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert remote._proc.returncode == 0
