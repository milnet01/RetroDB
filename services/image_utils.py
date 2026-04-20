# =============================================================================
# RETRODB - Image Standardization Utilities
# =============================================================================
# Standardizes images to consistent sizes using Real-ESRGAN (ONNX Runtime)
# for upscaling and Pillow Lanczos for downscaling. Applied on scraper
# download and via bulk tool for existing images.
# =============================================================================

import os
import logging
import queue
import threading

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy-loaded Real-ESRGAN ONNX singleton
# ---------------------------------------------------------------------------
_upscaler = None
_upscaler_checked = False
_gpu_failed = False
_upscaler_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Dedicated GPU inference thread
# ---------------------------------------------------------------------------
# MIOpen's compiled kernel invokers are stored in a per-handle in-memory
# cache, and ORT creates a separate MIOpen handle per thread (thread_local).
# If a different thread runs inference, it gets a new handle with an empty
# invoker cache → "No invoker was registered for convolution forward".
# Solution: funnel ALL GPU session.run() calls through a single dedicated
# thread so the same MIOpen handle (with its warm invoker cache) is reused.
# ---------------------------------------------------------------------------
_gpu_queue = None   # queue.Queue — items: (session, input_dict, Event, result_dict) or None to stop
_gpu_thread = None


def _gpu_inference_worker():
    """Process GPU inference requests on a single thread to keep MIOpen's
    per-thread invoker cache alive."""
    while True:
        item = _gpu_queue.get()
        if item is None:
            break
        session, input_dict, event, result = item
        try:
            result['output'] = session.run(None, input_dict)
        except Exception as e:
            result['error'] = e
        event.set()


def _gpu_run(session, input_dict):
    """Submit an inference request to the dedicated GPU thread and block
    until the result is ready."""
    result = {}
    event = threading.Event()
    _gpu_queue.put((session, input_dict, event, result))
    event.wait()
    if 'error' in result:
        raise result['error']
    return result['output']


_MODEL_URLS = [
    'https://huggingface.co/Xenova/realesrgan-x4plus/resolve/main/model.onnx',
    'https://huggingface.co/AXERA-TECH/Real-ESRGAN/resolve/main/onnx/realesrgan-x4.onnx',
]


def _download_model(url, dest):
    """Download the ONNX model file from a URL to dest path.

    Tries the given URL first, then falls back to alternate mirrors.
    Uses a browser-like User-Agent since some hosts block default urllib.
    """
    import urllib.request
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + '.tmp'

    urls_to_try = [url] + [u for u in _MODEL_URLS if u != url]
    last_err = None

    for try_url in urls_to_try:
        try:
            logger.info(f"Downloading Real-ESRGAN ONNX model from {try_url} …")
            req = urllib.request.Request(try_url, headers={
                'User-Agent': 'RetroDB/1.0 (ONNX model downloader)'
            })
            with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, 'wb') as f:
                while True:
                    chunk = resp.read(1024 * 256)
                    if not chunk:
                        break
                    f.write(chunk)
            os.replace(tmp, dest)
            logger.info("Model download complete")
            return
        except Exception as e:
            last_err = e
            logger.warning(f"Failed to download from {try_url}: {e}")
            if os.path.exists(tmp):
                os.remove(tmp)

    raise RuntimeError(f"All model download URLs failed. Last error: {last_err}")


class _OnnxUpscaler:
    """Real-ESRGAN x4 upscaler backed by ONNX Runtime with tiled inference."""

    # Max tiles before falling back to Lanczos.
    # CPU: ~0.4s/tile so 100 tiles = 40s max. GPU: ~0.05s/tile so 1024 tiles = 51s max.
    MAX_TILES_CPU = 100
    MAX_TILES_GPU = 1024

    def __init__(self, session, tile_size=256, tile_pad=10, gpu=False):
        self._session = session
        self._tile_size = tile_size
        self._tile_pad = tile_pad
        self._scale = 4
        self._gpu = gpu
        self.max_tiles = self.MAX_TILES_GPU if gpu else self.MAX_TILES_CPU
        # Detect whether model requires exact fixed-size input
        model_input = session.get_inputs()[0]
        shape = model_input.shape
        self._fixed_input = (len(shape) == 4
                             and isinstance(shape[2], int)
                             and isinstance(shape[3], int))

    def enhance(self, img_np, outscale=4):
        """Upscale a numpy RGB uint8 image by 4x using tiled inference.

        Args:
            img_np: HxWx3 numpy array, dtype uint8, RGB order.
            outscale: Kept for API compatibility (always 4x internally).

        Returns:
            (output_np, None) — output is HxWx3 uint8 RGB, or (None, None)
            if the image requires too many tiles (caller should fall back to Lanczos).
        """
        import numpy as np

        h, w = img_np.shape[:2]

        # Pad image so dimensions are multiples of tile_size
        tile = self._tile_size
        pad_h = (tile - h % tile) % tile
        pad_w = (tile - w % tile) % tile
        if pad_h or pad_w:
            img_np = np.pad(img_np, ((0, pad_h), (0, pad_w), (0, 0)), mode='reflect')

        ph, pw = img_np.shape[:2]
        scale = self._scale
        out = np.zeros((ph * scale, pw * scale, 3), dtype=np.float32)

        pad = self._tile_pad

        # Calculate tile grid
        tiles_y = max(1, ph // tile)
        tiles_x = max(1, pw // tile)
        total_tiles = tiles_y * tiles_x

        # Skip Real-ESRGAN if too many tiles (would stall bulk operations on CPU)
        if total_tiles > self.max_tiles:
            logger.info(f"Image {w}x{h} needs {total_tiles} tiles (limit {self.max_tiles}), using Lanczos instead")
            return None, None

        if total_tiles > 10:
            logger.debug(f"Real-ESRGAN: upscaling {w}x{h} image ({total_tiles} tiles)")

        input_name = self._session.get_inputs()[0].name

        for ty in range(tiles_y):
            for tx in range(tiles_x):
                # Input tile bounds
                y0 = ty * tile
                x0 = tx * tile
                y1 = y0 + tile
                x1 = x0 + tile

                # Add overlap padding (clamped to image bounds)
                y0p = max(y0 - pad, 0)
                x0p = max(x0 - pad, 0)
                y1p = min(y1 + pad, ph)
                x1p = min(x1 + pad, pw)

                # Extract tile and convert to float32 NCHW [0,1]
                tile_img = img_np[y0p:y1p, x0p:x1p, :]

                # For fixed-input models, ensure tile is exactly tile_size x tile_size
                if self._fixed_input:
                    th, tw = tile_img.shape[:2]
                    if th != tile or tw != tile:
                        padded = np.zeros((tile, tile, 3), dtype=tile_img.dtype)
                        padded[:th, :tw, :] = tile_img
                        tile_img = padded

                tile_f = tile_img.astype(np.float32) / 255.0
                tile_f = np.transpose(tile_f, (2, 0, 1))  # HWC → CHW
                tile_f = np.expand_dims(tile_f, 0)         # CHW → NCHW

                # Run inference (GPU: dispatch to dedicated thread to keep
                # MIOpen's invoker cache on the same handle)
                if self._gpu and _gpu_queue is not None:
                    result = _gpu_run(self._session, {input_name: tile_f})[0]
                else:
                    result = self._session.run(None, {input_name: tile_f})[0]

                # result is NCHW float32 [0,1] — convert to HWC
                result = np.squeeze(result, 0)              # NCHW → CHW
                result = np.transpose(result, (1, 2, 0))    # CHW → HWC

                # Calculate output region (strip overlap padding)
                oy0 = (y0 - y0p) * scale
                ox0 = (x0 - x0p) * scale
                oy1 = oy0 + tile * scale
                ox1 = ox0 + tile * scale

                # For fixed-input models with padding, crop result to actual tile area
                if self._fixed_input:
                    result = result[:tile * scale, :tile * scale, :]

                # Place into output
                out_y0 = y0 * scale
                out_x0 = x0 * scale
                out_y1 = y1 * scale
                out_x1 = x1 * scale
                out[out_y0:out_y1, out_x0:out_x1, :] = result[oy0:oy1, ox0:ox1, :]

        # Crop away padding added for tile alignment
        out = out[:h * scale, :w * scale, :]

        # Clamp and convert to uint8
        out = np.clip(out * 255.0, 0, 255).astype(np.uint8)
        return out, None


def _get_upscaler():
    """Return the Real-ESRGAN ONNX upscaler singleton, or None if unavailable."""
    global _upscaler, _upscaler_checked
    if _upscaler_checked:
        return _upscaler

    with _upscaler_lock:
        # Double-check after acquiring lock
        if _upscaler_checked:
            return _upscaler
        _init_upscaler(allow_gpu=not _gpu_failed)
        _upscaler_checked = True
    return _upscaler


def _init_upscaler(allow_gpu=True):
    """Initialize the ONNX upscaler session with the specified provider strategy."""
    global _upscaler
    try:
        import config
        import numpy as np
        # ROCm env vars (HSA_OVERRIDE_GFX_VERSION, MIOPEN_FIND_MODE, etc.)
        # are set at app startup in app.py before any ROCm libraries load.
        import onnxruntime as ort

        # Resolve model path — download from Hugging Face if not cached
        model_name = getattr(config, 'REALESRGAN_MODEL_NAME', 'RealESRGAN_x4plus')
        model_path = os.path.join(
            os.path.expanduser('~'), '.cache', 'realesrgan', f'{model_name}.onnx'
        )
        if not os.path.exists(model_path):
            model_url = getattr(
                config, 'REALESRGAN_MODEL_URL',
                'https://huggingface.co/Xenova/realesrgan-x4plus/resolve/main/model.onnx'
            )
            _download_model(model_url, model_path)

        # Prefer GPU providers, fall back to CPU
        # CUDA = NVIDIA, ROCm = AMD (prefer ROCm EP over MIGraphX — MIGraphX
        # does slow ahead-of-time compilation on first load)
        # Note: onnxruntime-rocm will abort() if GPU isn't accessible (e.g. user
        # not in render group). Pre-check /dev/kfd access before requesting GPU.
        available = set(ort.get_available_providers())
        providers = []
        if allow_gpu:
            _rocm_accessible = os.access('/dev/kfd', os.R_OK | os.W_OK)
            if 'CUDAExecutionProvider' in available:
                providers.append('CUDAExecutionProvider')
            if 'ROCMExecutionProvider' in available and _rocm_accessible:
                providers.append('ROCMExecutionProvider')
            elif 'ROCMExecutionProvider' in available:
                logger.warning("ROCm provider available but /dev/kfd not accessible (add user to 'render' group)")
        providers.append('CPUExecutionProvider')

        session = ort.InferenceSession(model_path, providers=providers)
        active = session.get_providers()

        # Auto-detect tile size from the model's expected input shape
        # Some ONNX models have fixed input dims (e.g. 64x64)
        model_input = session.get_inputs()[0]
        input_shape = model_input.shape  # e.g. [1, 3, 64, 64] or [1, 3, 'h', 'w']
        if (len(input_shape) == 4
                and isinstance(input_shape[2], int)
                and isinstance(input_shape[3], int)):
            tile_size = min(input_shape[2], input_shape[3])
            logger.info(f"Real-ESRGAN model expects fixed {input_shape[2]}x{input_shape[3]} tiles")
        else:
            tile_size = getattr(config, 'REALESRGAN_TILE_SIZE', 256)
        is_gpu = any(p in active for p in ('CUDAExecutionProvider', 'ROCMExecutionProvider'))
        _upscaler = _OnnxUpscaler(session, tile_size=tile_size, tile_pad=0 if tile_size <= 64 else 10, gpu=is_gpu)

        if 'CUDAExecutionProvider' in active:
            backend = 'CUDA'
        elif 'ROCMExecutionProvider' in active:
            backend = 'ROCm (AMD GPU)'
        else:
            backend = 'CPU'
        logger.info(f"Real-ESRGAN ONNX loaded ({backend} mode, tile={tile_size}px, max_tiles={_upscaler.max_tiles})")

        # GPU warm-up: spin up a dedicated inference thread, then run a dummy
        # inference through it so MIOpen benchmarks convolution algorithms and
        # populates the invoker cache ON THAT THREAD.  All future GPU inference
        # is funnelled through the same thread (via _gpu_queue) so the per-
        # handle invoker cache is always warm.
        if is_gpu:
            global _gpu_queue, _gpu_thread
            import time as _time

            # Start the dedicated GPU inference thread (daemon so it dies with the process)
            _gpu_queue = queue.Queue()
            _gpu_thread = threading.Thread(target=_gpu_inference_worker, daemon=True,
                                           name='gpu-inference')
            _gpu_thread.start()

            logger.info("Running GPU warm-up inference (MIOpen algorithm benchmarking)...")
            t0 = _time.monotonic()
            try:
                dummy = np.zeros((1, 3, tile_size, tile_size), dtype=np.float32)
                # Run warm-up THROUGH the dedicated thread so the MIOpen
                # invoker cache is populated on the thread that will serve
                # all future inference requests.
                _gpu_run(session, {model_input.name: dummy})
                elapsed = (_time.monotonic() - t0) * 1000
                logger.info(f"GPU warm-up complete ({elapsed:.0f}ms)")
            except Exception as warmup_err:
                elapsed = (_time.monotonic() - t0) * 1000
                logger.warning(f"GPU warm-up failed ({elapsed:.0f}ms): {warmup_err}")
                logger.warning("Falling back to CPU-only mode")
                # Stop the GPU thread — not needed for CPU mode
                _gpu_queue.put(None)
                _gpu_queue = None
                _gpu_thread = None
                # Rebuild session without GPU
                session = ort.InferenceSession(model_path, providers=['CPUExecutionProvider'])
                _upscaler = _OnnxUpscaler(session, tile_size=tile_size, tile_pad=0 if tile_size <= 64 else 10, gpu=False)
                backend = 'CPU'
                logger.info(f"Real-ESRGAN ONNX reloaded ({backend} mode, tile={tile_size}px, max_tiles={_upscaler.max_tiles})")

    except Exception as e:
        logger.warning(f"Real-ESRGAN unavailable — upscaling disabled: {e}")
        _upscaler = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def standardize_downloaded_image(path, image_type):
    """Convenience wrapper — standardize a freshly-downloaded image.

    Args:
        path: Absolute path to the image file.
        image_type: One of 'boxart', 'screenshots', 'boxart_3d', 'controllers', 'fanart'.
    """
    import config

    if not path or not os.path.exists(path):
        return

    if image_type in config.IMAGE_SKIP_TYPES:
        return

    if image_type in ('controllers', 'hardware'):
        target = config.IMAGE_TARGET_LONGEST_EDGE
        preserve_rgba = True
    else:
        target = config.IMAGE_TARGET_HEIGHT
        preserve_rgba = image_type == 'boxart_3d'  # 3D boxart often has transparency

    standardize_image(path, image_type, target, preserve_rgba)


def standardize_image(path, image_type, target, preserve_rgba=False):
    """Standardize a single image to the target size.

    For height-based types (boxart, screenshots, boxart_3d): target is the
    desired height; width scales proportionally.
    For longest-edge types (controllers): target is the desired longest edge.

    Images within the 80%-120% threshold band are skipped.
    Small images are upscaled with Real-ESRGAN then resized.
    Large images are downscaled with Pillow Lanczos.

    Args:
        path: Absolute path to the image file.
        image_type: 'boxart', 'screenshots', 'boxart_3d', or 'controllers'.
        target: Target size in pixels.
        preserve_rgba: If True, handle alpha channel during upscale.
    """
    import config
    from PIL import Image

    try:
        img = Image.open(path)
    except Exception as e:
        logger.warning(f"Image standardize: cannot open {path}: {e}")
        return

    # For controllers/hardware, crop excess transparent space first
    if image_type in ('controllers', 'hardware') and img.mode == 'RGBA':
        bbox = img.getbbox()
        if bbox:
            img = img.crop(bbox)

    # Determine current relevant dimension
    w, h = img.size
    if image_type in ('controllers', 'hardware'):
        current = max(w, h)
    else:
        current = h

    # Check threshold band
    ratio = current / target
    if config.IMAGE_UPSCALE_THRESHOLD <= ratio <= config.IMAGE_DOWNSCALE_THRESHOLD:
        # Close image handle before returning
        img.close()
        return

    if ratio < config.IMAGE_UPSCALE_THRESHOLD:
        img = _upscale_image(img, image_type, target, preserve_rgba)
    else:
        img = _downscale_image(img, image_type, target)

    if img is not None:
        _save_image(img, path)
        img.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _upscale_image(img, image_type, target, preserve_rgba):
    """Upscale image using Real-ESRGAN, then Lanczos resize to exact target.

    For RGBA images: separate alpha, upscale RGB, resize alpha, reattach.

    Returns:
        PIL.Image at exact target size, or original if upscaler unavailable.
    """
    import numpy as np
    from PIL import Image

    upscaler = _get_upscaler()

    if upscaler is None:
        # Fallback: Lanczos upscale (lower quality but still standardized)
        logger.debug(f"Real-ESRGAN unavailable, using Lanczos upscale for {os.path.basename(img.filename) if hasattr(img, 'filename') else 'image'}")
        return _downscale_image(img, image_type, target)

    has_alpha = preserve_rgba and img.mode == 'RGBA'

    try:
        if has_alpha:
            # Separate alpha channel
            r, g, b, a = img.split()
            rgb_img = Image.merge('RGB', (r, g, b))
            alpha_img = a

            # Upscale RGB
            rgb_np = np.array(rgb_img)
            output, _ = upscaler.enhance(rgb_np, outscale=4)
            if output is None:
                # Too many tiles — fall back to Lanczos
                return _downscale_image(img, image_type, target)
            upscaled_rgb = Image.fromarray(output)

            # Resize alpha to match upscaled size
            alpha_resized = alpha_img.resize(upscaled_rgb.size, Image.LANCZOS)

            # Reattach alpha
            img = Image.merge('RGBA', (*upscaled_rgb.split(), alpha_resized))
        else:
            # Convert to RGB for upscaling
            if img.mode != 'RGB':
                img = img.convert('RGB')
            img_np = np.array(img)
            output, _ = upscaler.enhance(img_np, outscale=4)
            if output is None:
                # Too many tiles — fall back to Lanczos
                return _downscale_image(img, image_type, target)
            img = Image.fromarray(output)

    except Exception as e:
        global _gpu_failed, _upscaler, _upscaler_checked, _gpu_queue, _gpu_thread
        if upscaler._gpu and not _gpu_failed:
            with _upscaler_lock:
                if not _gpu_failed:  # Double-check under lock
                    # Circuit breaker: GPU failed, rebuild session with CPU-only
                    _gpu_failed = True
                    _upscaler_checked = False
                    _upscaler = None
                    # Stop the dedicated GPU thread
                    if _gpu_queue is not None:
                        _gpu_queue.put(None)
                        _gpu_queue = None
                        _gpu_thread = None
                    logger.warning(f"Real-ESRGAN GPU inference failed — switching to CPU for all future upscales: {e}")
                    # Re-init with CPU-only
                    _init_upscaler(allow_gpu=False)
                    _upscaler_checked = True
        elif not _gpu_failed:
            logger.warning(f"Real-ESRGAN upscale failed, falling back to Lanczos: {e}")
        # img is still the original or partially processed — Lanczos resize anyway

    # Now resize to exact target
    return _downscale_image(img, image_type, target)


def _downscale_image(img, image_type, target):
    """Resize image to exact target using Lanczos.

    Returns:
        PIL.Image at target size.
    """
    from PIL import Image

    w, h = img.size

    if image_type in ('controllers', 'hardware'):
        # Longest edge
        if w >= h:
            new_w = target
            new_h = int(h * (target / w))
        else:
            new_h = target
            new_w = int(w * (target / h))
    else:
        # Height-based
        new_h = target
        new_w = int(w * (target / h))

    if new_w < 1:
        new_w = 1
    if new_h < 1:
        new_h = 1

    return img.resize((new_w, new_h), Image.LANCZOS)


def _save_image(img, path):
    """Save image preserving format with appropriate quality settings."""
    ext = os.path.splitext(path)[1].lower()

    try:
        if ext == '.webp':
            if img.mode == 'RGBA':
                img.save(path, 'WEBP', quality=85, lossless=False)
            else:
                img.save(path, 'WEBP', quality=85)
        elif ext in ('.jpg', '.jpeg'):
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            img.save(path, 'JPEG', quality=90)
        elif ext == '.png':
            img.save(path, 'PNG')
        elif ext == '.gif':
            img.save(path, 'GIF')
        else:
            # Unknown format — save as PNG
            img.save(path, 'PNG')
    except Exception as e:
        logger.error(f"Image standardize: failed to save {path}: {e}")
