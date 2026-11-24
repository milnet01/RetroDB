"""PASS-59-273: Museum background removal runs in a helper process that
exits when idle, so the server never holds rembg's model.

The server side is driven against small fake helpers that speak the pipe
format, and the real helper loop runs with a stand-in `rembg` module, so no
model loads here.
"""
import subprocess
import sys
import textwrap

import pytest

from services import rembg_worker, upscale_worker

_ROOT = str(upscale_worker.Path(upscale_worker.__file__).resolve().parent.parent)
_FAKE = textwrap.dedent('''
    import os, sys
    import numpy as np
    sys.path.insert(0, %r)
    from services.upscale_worker import _recv, _send
    action = sys.argv[1]
    kind, arr, _ = _recv(sys.stdin.buffer)
    if action == 'crash':
        os._exit(3)
    if action == 'ok':
        _send(sys.stdout.buffer, 'ok', np.frombuffer(b'CUT:' + arr.tobytes(), dtype=np.uint8))
    else:
        _send(sys.stdout.buffer, 'unavailable')
''' % _ROOT)
PHOTO = b'\x89PNG fake photo bytes'


def _remote(monkeypatch, *actions):
    remote = rembg_worker._RembgRemote()
    plan = list(actions)
    started = []

    def _argv():
        started.append(remote.cpu_only)
        return [sys.executable, '-c', _FAKE, plan.pop(0)]
    monkeypatch.setattr(remote, '_argv', _argv)
    return remote, started


def test_the_helper_is_started_with_its_own_flag():
    argv = rembg_worker._RembgRemote()._argv()
    assert argv[-1] == '--rembg-worker'
    assert upscale_worker._Remote()._argv()[-1] == '--upscale-worker'


def test_a_photo_comes_back_from_the_helper_as_bytes(monkeypatch):
    remote, _ = _remote(monkeypatch, 'ok')
    assert remote.remove(PHOTO) == b'CUT:' + PHOTO


def test_a_crash_moves_to_cpu_and_a_second_crash_turns_removal_off(monkeypatch):
    remote, started = _remote(monkeypatch, 'crash', 'crash')
    with pytest.raises(RuntimeError):
        remote.remove(PHOTO)
    with pytest.raises(RuntimeError):
        remote.remove(PHOTO)
    assert started == [False, True]
    assert remote.disabled and remote.remove(PHOTO) is None


def test_a_helper_without_rembg_turns_removal_off(monkeypatch):
    remote, started = _remote(monkeypatch, 'unavailable')
    assert remote.remove(PHOTO) is None
    assert remote.disabled and len(started) == 1


def test_get_offers_nothing_without_rembg(monkeypatch):
    monkeypatch.setattr(rembg_worker, '_installed', False)
    assert rembg_worker.get() is None


def test_the_museum_keeps_the_photo_when_the_helper_fails(monkeypatch):
    import routes.museum as museum

    class Broken:
        def remove(self, _data):
            raise RuntimeError('helper ended')
    monkeypatch.setattr(rembg_worker, 'get', lambda: Broken())
    assert museum._remove_background(PHOTO) == PHOTO


def test_the_museum_never_loads_rembg_itself(monkeypatch):
    import routes.museum as museum
    sent = []

    class Remover:
        def remove(self, data):
            sent.append(data)
            return b'cut'
    monkeypatch.setattr(rembg_worker, 'get', lambda: Remover())
    # An earlier test may have left rembg loaded; start from a clean slate so
    # 'not loaded afterwards' means something. Restored at teardown.
    monkeypatch.delitem(sys.modules, 'rembg', raising=False)
    assert museum._remove_background(PHOTO) == b'cut'
    assert sent == [PHOTO]
    assert 'rembg' not in sys.modules


def test_the_real_helper_falls_back_to_cpu_then_exits_when_idle():
    """child_main with a stand-in rembg whose GPU session fails at run time."""
    script = textwrap.dedent('''
        import sys, types
        fake = types.ModuleType('rembg')
        made = []
        def new_session(model, providers=None):
            made.append(providers)
            return {'gpu': providers != ['CPUExecutionProvider']}
        def remove(data, session=None, post_process_mask=False):
            if session['gpu']:
                raise RuntimeError('MIOPEN failure')
            return b'cut:' + data + str(len(made)).encode()
        fake.new_session, fake.remove = new_session, remove
        sys.modules['rembg'] = fake
        from services import rembg_worker, upscale_worker
        upscale_worker.IDLE_SECONDS = 1
        upscale_worker._log_to_file = lambda *_a: None
        rembg_worker._model_missing = lambda: False
        rembg_worker._providers = lambda cpu: ['CPUExecutionProvider'] if cpu else ['ROCMExecutionProvider']
        rembg_worker.child_main([])
    ''')
    import numpy as np
    proc = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, cwd=_ROOT)
    upscale_worker._send(proc.stdin, 'work', np.frombuffer(_PNG, dtype=np.uint8))
    kind, out, _ = upscale_worker._recv(proc.stdout)
    assert kind == 'ok' and out.tobytes() == b'cut:' + _PNG + b'2'   # GPU session, then CPU
    upscale_worker._send(proc.stdin, 'work', np.frombuffer(_PNG, dtype=np.uint8))
    kind, out, _ = upscale_worker._recv(proc.stdout)
    assert out.tobytes() == b'cut:' + _PNG + b'2'                     # CPU session kept
    assert proc.wait(timeout=10) == 0


def _png():
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.new('RGB', (2, 2), 'red').save(buf, 'PNG')
    return buf.getvalue()


_PNG = _png()


def test_a_file_that_is_not_a_picture_keeps_the_gpu():
    """PASS-59-280: a bad upload is refused before the session, so it no
    longer moves background removal to CPU for good."""
    script = textwrap.dedent('''
        import sys, types
        fake = types.ModuleType('rembg')
        made = []
        def new_session(model, providers=None):
            made.append(providers)
            return {}
        def remove(data, session=None, post_process_mask=False):
            return b'cut:' + str(made).encode()
        fake.new_session, fake.remove = new_session, remove
        sys.modules['rembg'] = fake
        from services import rembg_worker, upscale_worker
        upscale_worker.IDLE_SECONDS = 1
        upscale_worker._log_to_file = lambda *_a: None
        rembg_worker._model_missing = lambda: False
        rembg_worker._providers = lambda cpu: ['CPUExecutionProvider'] if cpu else ['ROCMExecutionProvider']
        rembg_worker.child_main([])
    ''')
    import numpy as np
    proc = subprocess.Popen([sys.executable, '-c', script], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, cwd=_ROOT)
    upscale_worker._send(proc.stdin, 'work', np.frombuffer(b'not a picture', dtype=np.uint8))
    kind, _, text = upscale_worker._recv(proc.stdout)
    assert kind == 'error' and 'not a picture' in text
    upscale_worker._send(proc.stdin, 'work', np.frombuffer(_PNG, dtype=np.uint8))
    kind, out, _ = upscale_worker._recv(proc.stdout)
    assert kind == 'ok' and out.tobytes() == b"cut:[['ROCMExecutionProvider']]"
    assert proc.wait(timeout=10) == 0


def test_rocm_is_left_out_when_dev_kfd_is_not_usable(monkeypatch):
    import types
    fake = types.ModuleType('onnxruntime')
    fake.get_available_providers = lambda: ['ROCMExecutionProvider', 'CPUExecutionProvider']
    monkeypatch.setitem(sys.modules, 'onnxruntime', fake)
    monkeypatch.setattr(rembg_worker.os, 'access', lambda *_a: False)
    assert rembg_worker._providers(False) == ['CPUExecutionProvider']
    monkeypatch.setattr(rembg_worker.os, 'access', lambda *_a: True)
    assert rembg_worker._providers(False) == ['ROCMExecutionProvider', 'CPUExecutionProvider']
