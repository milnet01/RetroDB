"""PASS-59-269: the AI upscaler runs in a helper process.

The server side (`upscale_worker._Remote`) is driven against small fake
helpers that speak the same pipe format, so no model loads here.
"""
import subprocess
import sys
import textwrap

import numpy as np
import pytest

from services import upscale_worker

# A fake helper: answers each request by the action named in its argv.
_ROOT = str(upscale_worker.Path(upscale_worker.__file__).resolve().parent.parent)
_FAKE = textwrap.dedent('''
    import os, sys
    sys.path.insert(0, %r)
    from services.upscale_worker import _recv, _send
    action = sys.argv[1]
    kind, arr, _ = _recv(sys.stdin.buffer)
    if action == 'crash':
        os._exit(3)
    if action == 'idle':
        os._exit(0)
    if action == 'ok':
        _send(sys.stdout.buffer, 'ok', arr * 2)
    else:
        _send(sys.stdout.buffer, 'unavailable')
''' % _ROOT)
_IMG = np.arange(12, dtype=np.uint8).reshape(2, 2, 3)


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
    out, extra = remote.enhance(_IMG)
    assert extra is None and (out == _IMG * 2).all()


def test_a_helper_that_left_for_idleness_is_restarted_once(monkeypatch):
    remote, started = _remote(monkeypatch, 'idle', 'ok')
    assert (remote.enhance(_IMG)[0] == _IMG * 2).all()
    assert len(started) == 2 and not remote.cpu_only


def test_a_crash_moves_to_cpu_and_a_second_crash_turns_upscaling_off(monkeypatch):
    remote, started = _remote(monkeypatch, 'crash', 'crash')
    with pytest.raises(RuntimeError):
        remote.enhance(_IMG)
    assert remote.cpu_only and not remote.disabled
    with pytest.raises(RuntimeError):
        remote.enhance(_IMG)
    assert started == [False, True]
    assert remote.disabled
    assert remote.enhance(_IMG) == (None, None)


def test_a_helper_with_no_upscaler_turns_upscaling_off(monkeypatch):
    remote, started = _remote(monkeypatch, 'unavailable')
    assert remote.enhance(_IMG) == (None, None)
    assert remote.disabled
    assert remote.enhance(_IMG) == (None, None) and len(started) == 1


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
        upscale_worker._log_to_file = lambda *_a: None
        image_utils._get_local_upscaler = lambda: object()
        image_utils._enhance_local = lambda arr: arr + 1
        upscale_worker.child_main([])
    ''')
    proc = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, cwd=_ROOT)
    upscale_worker._send(proc.stdin, 'enhance', _IMG)
    kind, out, _ = upscale_worker._recv(proc.stdout)
    assert kind == 'ok' and (out == _IMG + 1).all()
    assert proc.wait(timeout=10) == 0


def test_an_ended_helper_is_collected_without_waiting_for_the_next_upscale(monkeypatch):
    import time
    remote, _ = _remote(monkeypatch, 'ok')
    remote.enhance(_IMG)      # the fake helper exits after one reply
    deadline = time.monotonic() + 5
    while remote._proc.returncode is None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert remote._proc.returncode == 0
