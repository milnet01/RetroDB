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
    from services import upscale_worker
    from services.upscale_worker import _recv, _send
    action = sys.argv[1]
    kind, arr, _ = _recv(sys.stdin.buffer)
    if action == 'crash':
        os._exit(3)
    if action == 'idle':
        os._exit(0)
    if action == 'hung':
        os._exit(upscale_worker.GPU_HUNG_EXIT)
    if action == 'slow':
        import time
        for _ in range(5):
            time.sleep(0.4)
            _send(sys.stdout.buffer, 'wait')
        action = 'ok'
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


def test_a_helper_with_no_upscaler_is_asked_again_later(monkeypatch):
    """A failed first model download is often a passing fault (PASS-59-280)."""
    remote, started = _remote(monkeypatch, 'unavailable', 'ok')
    assert remote.enhance(_IMG) == (None, None)
    assert not remote.disabled
    assert remote.enhance(_IMG) == (None, None) and len(started) == 1
    remote.retry_at = 0.0        # RETRY_SECONDS have passed
    assert (remote.enhance(_IMG)[0] == _IMG * 2).all()
    assert len(started) == 2


def test_a_slow_model_download_is_not_killed_as_a_hang(monkeypatch):
    """Each 'wait' restarts the call's clock (PASS-59-280)."""
    monkeypatch.setattr(upscale_worker, 'CALL_TIMEOUT', 1)
    remote, started = _remote(monkeypatch, 'slow')
    assert (remote.enhance(_IMG)[0] == _IMG * 2).all()
    assert started == [False] and not remote.cpu_only


def test_a_helper_whose_gpu_hung_is_followed_by_a_cpu_one(monkeypatch):
    remote, started = _remote(monkeypatch, 'hung', 'ok')
    with pytest.raises(RuntimeError):
        remote.enhance(_IMG)
    assert remote.cpu_only and not remote.disabled
    assert (remote.enhance(_IMG)[0] == _IMG * 2).all()
    assert started == [False, True]


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


def test_the_helper_exits_to_free_a_hung_gpu():
    """PASS-59-156: a GPU call that timed out still holds the card, so the
    helper exits without replying instead of carrying on on CPU."""
    script = textwrap.dedent('''
        from services import image_utils, upscale_worker
        upscale_worker._log_to_file = lambda *_a: None
        image_utils._get_local_upscaler = lambda: object()
        def _hang(arr):
            image_utils._gpu_hung = True
            raise TimeoutError("GPU inference gave no result")
        image_utils._enhance_local = _hang
        upscale_worker.child_main([])
    ''')
    proc = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, cwd=_ROOT)
    upscale_worker._send(proc.stdin, 'work', _IMG)
    assert proc.stdout.read() == b''
    assert proc.wait(timeout=10) == upscale_worker.GPU_HUNG_EXIT


def test_the_helper_says_it_is_still_working_during_a_download():
    script = textwrap.dedent('''
        import time
        from services import image_utils, upscale_worker
        upscale_worker.KEEPALIVE_SECONDS = 0.2
        upscale_worker.IDLE_SECONDS = 1
        upscale_worker._log_to_file = lambda *_a: None
        def _load():
            with upscale_worker.still_working():
                time.sleep(1)
            return object()
        image_utils._get_local_upscaler = _load
        image_utils._enhance_local = lambda arr: arr
        upscale_worker.child_main([])
    ''')
    proc = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, cwd=_ROOT)
    upscale_worker._send(proc.stdin, 'work', _IMG)
    kinds = []
    while not kinds or kinds[-1] == 'wait':
        kinds.append(upscale_worker._recv(proc.stdout)[0])
    assert kinds[-1] == 'ok' and kinds.count('wait') >= 2
    assert proc.wait(timeout=10) == 0


def test_still_working_does_nothing_outside_a_helper():
    with upscale_worker.still_working():
        pass


def test_a_gpu_call_that_times_out_marks_the_gpu_hung(monkeypatch):
    import queue
    import threading
    from services import image_utils

    release = threading.Event()

    class _Stuck:
        def run(self, _names, _inputs):
            release.wait(10)
            return ['late']
    monkeypatch.setattr(image_utils, '_GPU_RUN_TIMEOUT', 0.3)
    monkeypatch.setattr(image_utils, '_gpu_hung', False)
    monkeypatch.setattr(image_utils, '_gpu_queue', queue.Queue())
    worker = threading.Thread(target=image_utils._gpu_inference_worker, daemon=True)
    worker.start()
    try:
        with pytest.raises(TimeoutError):
            image_utils._gpu_run(_Stuck(), {})
        assert image_utils._gpu_hung
    finally:
        release.set()
        image_utils._gpu_queue.put(None)
        worker.join(5)
