"""The AI upscaler in its own process (PASS-59-269).

Real-ESRGAN loads onnxruntime and, on an AMD card, the ROCm libraries:
several hundred MB that a Python process never gives back. So the server
never loads them. The first image that needs an upscale starts a helper
process (`app.py --upscale-worker`, or the standalone binary with that
flag), which loads the model and upscales one image at a time sent over
its stdin/stdout pipes. It exits after `IDLE_SECONDS` without work, and
the next upscale starts it again.

Inside the helper, `image_utils._get_local_upscaler()` and its GPU thread
and GPU-to-CPU breaker work as before (docs/specs/image-pipeline.md §5).
Here, in the server: a helper that crashes in an upscale is followed by a
CPU-only one; a CPU-only helper that crashes turns upscaling off until
the server restarts. Every failure raises, and the caller falls back to
Lanczos.
"""
from __future__ import annotations

import importlib.util
import io
import json
import logging
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

FLAG = '--upscale-worker'
CPU_FLAG = '--cpu'
IDLE_SECONDS = 120
# One call's ceiling: model download and warm-up on a first call, then up
# to the tile cap (about a minute on GPU or CPU). A helper past it is killed.
CALL_TIMEOUT = 600
_LOG_NAME = 'upscale_worker.log'
_LOG_MAX_BYTES = 5 * 1024 * 1024


# -----------------------------------------------------------------------------
# The pipe: a 4-byte length, a JSON header, then a .npy array when the header
# says so. No pickle, so neither side can be made to run code by the other.
# -----------------------------------------------------------------------------

def _send(stream, kind, arr=None, text=''):
    payload = b''
    if arr is not None:
        import numpy as np
        buf = io.BytesIO()
        np.save(buf, np.asarray(arr), allow_pickle=False)
        payload = buf.getvalue()
    header = json.dumps({'kind': kind, 'text': text, 'array': arr is not None,
                         'size': len(payload)}).encode()
    stream.write(len(header).to_bytes(4, 'big') + header + payload)
    stream.flush()


def _read_exact(stream, n):
    data = stream.read(n)
    if len(data) != n:
        raise EOFError('pipe closed')
    return data


def _recv(stream):
    """(kind, array or None, text). EOFError when the pipe has closed."""
    header = json.loads(_read_exact(stream, int.from_bytes(_read_exact(stream, 4), 'big')))
    arr = None
    if header['array']:
        import numpy as np
        arr = np.load(io.BytesIO(_read_exact(stream, header['size'])), allow_pickle=False)
    return header['kind'], arr, header['text']


# -----------------------------------------------------------------------------
# Server side
# -----------------------------------------------------------------------------

class _Remote:
    """Stands in for the upscaler: `enhance()` sends the image to the helper."""

    _gpu = False   # the helper owns the GPU and its breaker

    def __init__(self):
        self._lock = threading.Lock()
        self._proc = None
        self.cpu_only = False
        self.disabled = False

    def _argv(self):
        if getattr(sys, 'frozen', False):
            argv = [sys.executable, FLAG]
        else:
            argv = [sys.executable, str(Path(__file__).resolve().parent.parent / 'app.py'), FLAG]
        return argv + ([CPU_FLAG] if self.cpu_only else [])

    def _start(self):
        flags = getattr(subprocess, 'CREATE_NO_WINDOW', 0)   # Windows: no console
        self._proc = subprocess.Popen(
            self._argv(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, creationflags=flags)
        # Collect its exit status as soon as it ends, idle or not, so it
        # does not linger as a zombie until the next upscale.
        threading.Thread(target=self._proc.wait, daemon=True,
                         name='upscale-helper-reaper').start()
        logger.info(f"Upscale helper started (pid {self._proc.pid}"
                    f"{', CPU only' if self.cpu_only else ''})")

    def _ask(self, arr):
        if self._proc is None or self._proc.poll() is not None:
            self._start()
        proc = self._proc
        watchdog = threading.Timer(CALL_TIMEOUT, proc.kill)
        watchdog.start()
        try:
            _send(proc.stdin, 'enhance', arr)
            return _recv(proc.stdout)
        finally:
            watchdog.cancel()

    def _ended(self):
        """The helper's exit code once its pipe has closed."""
        try:
            return self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            return self._proc.wait()

    def enhance(self, arr, outscale=4):
        """(upscaled array, None), or (None, None) when the image is over
        the tile cap or no upscaler can load. Raises when the helper fails."""
        with self._lock:
            if self.disabled:
                return None, None
            for attempt in (1, 2):
                try:
                    reply = self._ask(arr)
                    break
                except (EOFError, OSError, ValueError) as e:
                    code = self._ended()
                    if code == 0 and attempt == 1:
                        continue    # it left for idleness as the image went in
                    if self.cpu_only:
                        self.disabled = True
                        logger.warning(f"Upscale helper crashed again on CPU (exit {code}); "
                                       f"AI upscaling is off until the server restarts")
                    else:
                        self.cpu_only = True
                        logger.warning(f"Upscale helper crashed (exit {code}); "
                                       f"the next one runs on CPU only")
                    raise RuntimeError(f"upscale helper ended: {e!r}") from e
            kind, out, text = reply
            if kind == 'ok':
                return out, None
            if kind == 'unavailable':
                self.disabled = True
                logger.warning("Real-ESRGAN could not load in the upscale helper; "
                               "see logs/upscale_worker.log. Upscaling uses Lanczos.")
                return None, None
            raise RuntimeError(text)


_remote = _Remote()
_installed = None


def get():
    """The upscaler stand-in, or None when onnxruntime is not installed."""
    global _installed
    if _installed is None:
        _installed = importlib.util.find_spec('onnxruntime') is not None
    return _remote if _installed and not _remote.disabled else None


# -----------------------------------------------------------------------------
# Helper side
# -----------------------------------------------------------------------------

def _log_to_file():
    """Send fds 1 and 2, and Python logging, to logs/upscale_worker.log, so
    native libraries' messages (a missing ROCm library) are kept there."""
    import config
    path = os.path.join(config.BASE_DIR, 'logs', _LOG_NAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path) and os.path.getsize(path) > _LOG_MAX_BYTES:
        os.replace(path, path + '.1')
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    sys.stdout = sys.stderr = open(2, 'w', buffering=1, closefd=False)
    logging.basicConfig(level=logging.INFO, stream=sys.stderr, force=True,
                        format='%(asctime)s - upscale_worker - %(name)s - %(levelname)s - %(message)s')


def child_main(argv):
    """Serve upscales until stdin closes or IDLE_SECONDS pass without one."""
    replies = os.fdopen(os.dup(1), 'wb')      # the pipe, before fd 1 moves
    requests = os.fdopen(os.dup(0), 'rb')
    _log_to_file()
    from services import image_utils
    if CPU_FLAG in argv:
        image_utils._gpu_failed = True

    inbox = queue.Queue()

    def _read():
        try:
            while True:
                inbox.put(_recv(requests))
        except Exception:
            inbox.put(None)     # the server closed the pipe
    threading.Thread(target=_read, daemon=True).start()

    while True:
        try:
            item = inbox.get(timeout=IDLE_SECONDS)
        except queue.Empty:
            break
        if item is None:
            break
        try:
            if image_utils._get_local_upscaler() is None:
                _send(replies, 'unavailable')
            else:
                # None when the image is over the tile cap
                _send(replies, 'ok', image_utils._enhance_local(item[1]))
        except Exception as e:
            _send(replies, 'error', text=f"{type(e).__name__}: {e}")
    # os._exit skips exit handlers: ROCm's roctracer aborts in them and
    # leaves a core dump behind.
    replies.flush()
    os._exit(0)
