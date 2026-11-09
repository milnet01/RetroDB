"""Museum background removal in its own process (PASS-59-273).

rembg's birefnet-general model is a 973 MB file. Measured 2026-11-09 on the
CPU path, loading it takes a process to about 2.1 GB and one removal to about
9 GB, and Python does not give that memory back while the process lives. So
the server never loads it. The first photo that needs its background removed
starts a helper (`app.py --rembg-worker`, or the standalone binary with that
flag), on the same machinery as the upscale helper (`upscale_worker`): one
photo at a time over its pipes, and it exits after `IDLE_SECONDS` without
work. A separate process from the upscaler, so the two models are never
loaded together.

Inside the helper a GPU session that fails at run time is replaced by a CPU
one. A helper that crashes outright is followed by a CPU-only helper; one
that crashes on CPU turns background removal off until the server restarts.
The caller then keeps the photo as it was.
"""
from __future__ import annotations

import importlib.util
import logging

from services import upscale_worker

logger = logging.getLogger(__name__)

FLAG = '--rembg-worker'
MODEL = 'birefnet-general'
_LOG_NAME = 'rembg_worker.log'


class _RembgRemote(upscale_worker._Remote):
    FLAG = FLAG
    NAME = 'Background-removal'

    def remove(self, image_bytes):
        """The photo as PNG bytes with its background removed, or None when
        rembg cannot load. Raises RuntimeError when the helper fails."""
        import numpy as np
        with self._lock:
            if self.disabled:
                return None
            kind, out, text = self._call(np.frombuffer(image_bytes, dtype=np.uint8))
            if kind == 'ok':
                return out.tobytes()
            if kind == 'unavailable':
                self.disabled = True
                logger.warning("rembg could not load in its helper; see logs/%s. "
                               "Background removal is off.", _LOG_NAME)
                return None
            raise RuntimeError(text)


_remote = _RembgRemote()
_installed = None


def get():
    """The background-removal stand-in, or None when rembg is not installed
    or removal has been turned off."""
    global _installed
    if _installed is None:
        _installed = importlib.util.find_spec('rembg') is not None
    return _remote if _installed and not _remote.disabled else None


# -----------------------------------------------------------------------------
# Helper side
# -----------------------------------------------------------------------------

def _providers(cpu_only):
    """GPU providers first when onnxruntime offers one, else CPU."""
    if cpu_only:
        return ['CPUExecutionProvider']
    import onnxruntime as ort
    available = ort.get_available_providers()
    preferred = ['CUDAExecutionProvider', 'ROCMExecutionProvider',
                 'CoreMLExecutionProvider', 'CPUExecutionProvider']
    return [p for p in preferred if p in available] or None


def child_main(argv):
    """Remove backgrounds until stdin closes or IDLE_SECONDS pass without one."""
    import numpy as np
    state = {'session': None, 'cpu': upscale_worker.CPU_FLAG in argv}

    def _remove(arr):
        try:
            from rembg import remove, new_session
        except ImportError:
            return 'unavailable', None, ''
        data = arr.tobytes()
        if state['session'] is None:
            providers = _providers(state['cpu'])
            logger.info("rembg %s using %s", MODEL, providers)
            state['session'] = new_session(MODEL, providers=providers)
        try:
            out = remove(data, session=state['session'], post_process_mask=True)
        except Exception as e:
            if state['cpu']:
                raise
            # A GPU session that fails at run time: carry on with CPU.
            logger.warning("rembg GPU failed (%s); switching to CPU", e)
            state['cpu'] = True
            state['session'] = new_session(MODEL, providers=['CPUExecutionProvider'])
            out = remove(data, session=state['session'], post_process_mask=True)
        return 'ok', np.frombuffer(out, dtype=np.uint8), ''

    upscale_worker.serve(_remove, _LOG_NAME)
