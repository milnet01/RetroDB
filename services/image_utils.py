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
import tempfile
import threading

logger = logging.getLogger(__name__)


# Pass 45.6 — Pillow decompression-bomb cap. A 1 MB malicious PNG can
# advertise dimensions that decode to 4+ GB of pixel data, OOM-killing
# the worker. Pillow has a built-in cap (`Image.MAX_IMAGE_PIXELS`,
# default ~89 megapixels) that emits a `DecompressionBombWarning`, but
# it doesn't *raise* unless the value is set explicitly OR a stricter
# value is configured. We set the cap once at module import so every
# `Image.open` call site below inherits it. Pass 41.14.A applied this
# only to `compute_dhash` in `image_dedup`; here we cover the rest of
# the image stack (`_validate_image_bytes`, `_atomic_save`,
# `standardize_image`, `finalize_downloaded_image`, `_OnnxUpscaler`).
try:
    from PIL import Image as _PIL_Image
    import config as _config
    _PIL_Image.MAX_IMAGE_PIXELS = getattr(_config, 'IMAGE_MAX_PIXELS', None) or 64_000_000
    del _PIL_Image, _config
except ImportError:
    # Pillow is a hard runtime dependency; if it really is missing,
    # individual call sites below will raise on their own `from PIL
    # import Image` and the cap is moot.
    pass


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

    Pass 41.14.B — every URL is run through `services.ssrf.validate_
    outbound_url(require_https=True)` before dereference. `_MODEL_URLS` is
    a hardcoded HuggingFace allowlist today, so the gate currently never
    rejects anything; it's defensive against any future code path that
    surfaces the URL via settings (a primitive that landed for `ROM_PATH`
    in Pass 32.1) and bypasses outbound-URL hygiene.

    Pass 45.2 — switched from urllib (which auto-follows redirects through
    real DNS) to requests + validate_and_pin_url + pin_host_ip so the GET
    connects to the same IP that the SSRF gate just verified, defeating
    DNS rebinding between validate and dereference.
    """
    import requests
    from services.ssrf import validate_outbound_url, validate_and_pin_url, pin_host_ip
    from urllib.parse import urlparse as _urlparse
    os.makedirs(os.path.dirname(dest), exist_ok=True)

    urls_to_try = [url] + [u for u in _MODEL_URLS if u != url]
    last_err = None
    dest_dir = os.path.dirname(dest) or '.'

    for try_url in urls_to_try:
        ok, reason, _ = validate_outbound_url(try_url, require_https=True)
        if not ok:
            last_err = RuntimeError(f"SSRF guard rejected {try_url}: {reason}")
            logger.warning(f"Skipping model URL (SSRF): {try_url} — {reason}")
            continue
        safe_url, pinned_ip, err = validate_and_pin_url(
            requests, try_url, max_redirects=3, timeout=10, require_https=True,
        )
        if err:
            last_err = RuntimeError(f"SSRF guard rejected redirect chain for {try_url}: {err}")
            logger.warning(f"Skipping model URL (SSRF redirect): {try_url} — {err}")
            continue
        pinned_host = _urlparse(safe_url).hostname
        # Pass 45.5 — mkstemp gives every download attempt its own tmp
        # path; the previous static suffix raced with concurrent
        # processes and could clobber an in-flight download from another
        # worker.
        tmp_fd, tmp = tempfile.mkstemp(prefix='.model_', suffix='.tmp', dir=dest_dir)
        os.close(tmp_fd)
        try:
            logger.info(f"Downloading Real-ESRGAN ONNX model from {safe_url} …")
            headers = {'User-Agent': 'RetroDB/1.0 (ONNX model downloader)'}
            with pin_host_ip(pinned_host, pinned_ip), requests.get(
                safe_url, headers=headers, timeout=120,
                stream=True, allow_redirects=False,
            ) as resp:
                resp.raise_for_status()
                with open(tmp, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 256):
                        if chunk:
                            f.write(chunk)
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except OSError:
                        pass
            os.replace(tmp, dest)
            logger.info("Model download complete")
            return
        except Exception as e:
            last_err = e
            logger.warning(f"Failed to download from {try_url}: {e}")
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

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


# Repair script surfaced when a GPU provider was requested but silently fell
# back to CPU (usually a missing ROCm system library after a ROCm upgrade).
_ROCM_REPAIR_SCRIPT = 'scripts/fix_onnxruntime_rocm_rocsolver.sh'
_GPU_PROVIDERS = ('ROCMExecutionProvider', 'CUDAExecutionProvider')


def _gpu_fallback_warning(requested, active):
    """Return an actionable warning when a GPU provider was requested but none
    activated (so inference silently fell back to CPU), else None.

    The usual cause on the AMD box is a missing ROCm system library
    (e.g. librocsolver.so.0) after a ROCm upgrade: onnxruntime logs a cryptic
    provider-load error and drops to CPU. This turns that into a clear pointer
    at the repair script.
    """
    requested_gpu = [p for p in requested if p in _GPU_PROVIDERS]
    if not requested_gpu or any(p in active for p in _GPU_PROVIDERS):
        return None
    return (
        f"Real-ESRGAN: GPU provider(s) {requested_gpu} requested but none "
        f"activated — running on CPU. This usually means a ROCm/CUDA system "
        f"library failed to load (often after a ROCm upgrade); see the "
        f"onnxruntime error logged above for the exact library. To repair, run "
        f"`{_ROCM_REPAIR_SCRIPT}` then restart."
    )


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

        # Surface a silent GPU->CPU fallback with a pointer to the repair script.
        _fallback_msg = _gpu_fallback_warning(providers, active)
        if _fallback_msg:
            logger.warning(_fallback_msg)

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

# Image types where the pipeline may convert format on ingest. Videos and
# manuals keep their original extension; GIFs preserve animation.
_CONVERTIBLE_TYPES = frozenset({
    'boxart', 'boxart_3d', 'screenshots', 'fanart', 'controllers', 'hardware',
})

_PIL_FORMAT_FOR_EXT = {
    '.webp': 'WEBP',
    '.jpg':  'JPEG',
    '.jpeg': 'JPEG',
    '.png':  'PNG',
    '.gif':  'GIF',
}


def preferred_image_extension(image_type, original_ext='.jpg'):
    """Return the on-disk extension new downloads of `image_type` should use.

    Driven by `config.IMAGE_FORMAT`. GIFs pass through unchanged so animations
    survive. Non-convertible types (video, manual) keep their original ext.
    """
    import config

    if not original_ext.startswith('.'):
        original_ext = '.' + original_ext
    original_ext = original_ext.lower()

    if image_type not in _CONVERTIBLE_TYPES:
        return original_ext
    if original_ext == '.gif':
        return '.gif'

    fmt = getattr(config, 'IMAGE_FORMAT', 'webp').lower()
    if fmt == 'webp':
        return '.webp'
    # jpeg mode: keep original if already JPEG-ish, else downgrade to jpg
    return original_ext if original_ext in ('.jpg', '.jpeg') else '.jpg'


def _ensure_format_matches_extension(path):
    """If the on-disk bytes at `path` don't match the filename extension
    (e.g. JPEG bytes written to a `.webp` filename because the caller chose
    the target format up-front), re-encode in place. No-op when the format
    already matches or Pillow can't decode the file.
    """
    from PIL import Image

    ext = os.path.splitext(path)[1].lower()
    target = _PIL_FORMAT_FOR_EXT.get(ext)
    if not target:
        return

    try:
        with Image.open(path) as img:
            current = (img.format or '').upper()
            if current == target:
                return
            # Copy the decoded pixels so we can close the source handle
            # before overwriting it (Windows file-lock safety).
            img.load()
            buffer = img.copy()
        _save_image(buffer, path)
        buffer.close()
    except Image.DecompressionBombError as e:
        # Pass 45.6 — log decompression bombs distinctly so the security
        # log shows the rejected filename (a normal "format normalize
        # failed" line could otherwise hide a bomb attempt).
        logger.warning(f"Image format normalize: decompression bomb rejected for {path} ({e})")
    except Exception as e:
        logger.warning(f"Image format normalize failed for {path}: {e}")


def finalize_downloaded_image(path, image_type):
    """Post-download pipeline.

    1. Re-encode bytes to match the filename extension (so callers can declare
       the target format via the path alone — e.g. `foo.webp` will be WebP on
       disk even if the source URL served JPEG).
    2. Run the existing size standardization pass (Real-ESRGAN / Lanczos).
    3. Generate responsive `-sm` / `-md` variants for boxart.

    Safe to call from any scraper call site — each step is best-effort and
    swallows its own errors so the caller never fails a download on
    post-processing trouble.
    """
    if not path or not os.path.exists(path):
        return

    _ensure_format_matches_extension(path)
    standardize_downloaded_image(path, image_type)
    _make_responsive_variants(path, image_type)


# Responsive boxart variants: keep cards light without touching the original.
# Sizes chosen to match the actual render widths: ~150 px for grid cards,
# ~300 px for modals / detail views. The HTMLImageElement picks the smallest
# candidate that satisfies its layout width, so serving two variants cuts
# payload 60-80% on list pages.
_RESPONSIVE_VARIANTS = {
    'boxart':    [('sm', 160), ('md', 320)],
    'boxart_3d': [('sm', 160), ('md', 320)],
}


def _variant_path(original_path, suffix):
    """Return the sibling path for a `-sm` / `-md` variant of `original_path`."""
    stem, ext = os.path.splitext(original_path)
    return f"{stem}-{suffix}{ext}"


def _make_responsive_variants(path, image_type):
    """Write `-sm` and `-md` sibling files for boxart-family images.

    Variants are Lanczos-downscaled and saved in the same format as the
    original. Missing / unreadable inputs silently no-op. Variants are
    regenerated unconditionally on each call (matches what happens during a
    full re-scrape) so they stay in sync with the primary image.
    """
    from PIL import Image

    sizes = _RESPONSIVE_VARIANTS.get(image_type)
    if not sizes or not os.path.exists(path):
        return

    try:
        with Image.open(path) as img:
            img.load()
            src_w, src_h = img.size
            for suffix, target_w in sizes:
                variant_file = _variant_path(path, suffix)
                if src_w <= target_w:
                    # Source is already smaller than the variant target —
                    # skip to avoid upscaling the variant unnecessarily.
                    # Pass 48.3 — but if a larger original previously produced
                    # this variant and the primary has since shrunk (e.g. a
                    # re-scrape at lower resolution), the stale sibling would
                    # still be picked up by boxart_srcset. Prune it so srcset
                    # never serves a variant wider than the current primary.
                    if os.path.exists(variant_file):
                        try:
                            os.remove(variant_file)
                        except OSError as e:
                            logger.warning(f"Could not prune stale variant {variant_file}: {e}")
                    continue
                ratio = target_w / src_w
                new_h = max(1, int(src_h * ratio))
                variant = img.resize((target_w, new_h), Image.LANCZOS)
                _save_image(variant, variant_file)
                variant.close()
    except Image.DecompressionBombError as e:
        logger.warning(f"Responsive variants: decompression bomb rejected for {path} ({e})")
    except Exception as e:
        logger.warning(f"Responsive variant generation failed for {path}: {e}")


def boxart_srcset(filename, sizes=None, image_type='boxart', existing=None):
    """Return a `srcset` string for a boxart filename, skipping missing variants.

    `filename` is the bare filename stored in the DB (e.g. `12_tgdb.webp`).
    `image_type` is the subdirectory under `static/images/` — `boxart` (default)
    or `boxart_3d`. The original plus each existing `-sm` / `-md` sibling is
    included so the browser can pick the smallest candidate that satisfies the
    rendered width. Returns an empty string when the original is missing.

    `existing` is an optional pre-computed set of filenames in the target
    directory (see `boxart_dir_listing()`). Supplying it lets the caller batch
    existence checks across many filenames — the function then skips the
    per-file `os.path.exists` calls and the PIL `Image.open` width read, using
    a conservative fallback (760 w) for the original's width descriptor.
    Without it, the function falls back to the per-file path used by the
    detail-page hero `<img>`.
    """
    import config

    if not filename:
        return ''

    boxart_dir = os.path.join(config.IMAGE_PATH, image_type)

    if existing is not None:
        if filename not in existing:
            return ''
        candidates = []
        for suffix, target_w in (sizes or _RESPONSIVE_VARIANTS.get(image_type, _RESPONSIVE_VARIANTS['boxart'])):
            variant_filename = os.path.basename(_variant_path(filename, suffix))
            if variant_filename in existing:
                candidates.append(f"/static/images/{image_type}/{variant_filename} {target_w}w")
        # Skip PIL open in batch mode — 500 PIL reads per request defeats the
        # whole point of grid-card srcset. The 760 fallback is a 7:10 boxart
        # ratio at the standardized 1080 height; the browser only picks the
        # original when DPR demands it.
        candidates.append(f"/static/images/{image_type}/{filename} 760w")
        return ', '.join(candidates) if candidates else ''

    original_path = os.path.join(boxart_dir, filename)
    if not os.path.exists(original_path):
        return ''

    candidates = []
    for suffix, target_w in (sizes or _RESPONSIVE_VARIANTS.get(image_type, _RESPONSIVE_VARIANTS['boxart'])):
        variant_filename = os.path.basename(_variant_path(filename, suffix))
        if os.path.exists(os.path.join(boxart_dir, variant_filename)):
            candidates.append(f"/static/images/{image_type}/{variant_filename} {target_w}w")

    # Width descriptor for the original: use actual pixel width when cheap to
    # read; otherwise fall back to a conservative upper bound (the
    # standardized target height of 1080 implies ~760 w for a 7:10 ratio).
    try:
        from PIL import Image
        with Image.open(original_path) as img:
            orig_w = img.size[0]
    except Image.DecompressionBombError as e:
        logger.warning(f"boxart_srcset: decompression bomb rejected for {original_path} ({e})")
        orig_w = 760
    except Exception:
        orig_w = 760
    candidates.append(f"/static/images/{image_type}/{filename} {orig_w}w")

    return ', '.join(candidates)


def boxart_dir_listing(image_type='boxart'):
    """Return the set of filenames in `static/images/<image_type>/`.

    Used by `build_game_card()` to batch-check boxart existence across many
    cards per request (one `os.scandir` instead of N `os.path.exists` + N
    `PIL.Image.open` calls). The result is cached on `flask.g` for the
    lifetime of the request — call this once before a card-rendering loop and
    pass the returned set to `boxart_srcset(filename, existing=...)`.

    Returns an empty set if the directory is missing or unreadable, so callers
    can pass the result through unconditionally — `'' in empty_set` is `False`
    and `boxart_srcset` correctly returns `''` when the file is unknown.
    """
    import config

    cache_attr = f'_boxart_listing_{image_type}'
    try:
        from flask import g, has_request_context
        if has_request_context():
            cached = getattr(g, cache_attr, None)
            if cached is not None:
                return cached
    except Exception:
        has_request_context = lambda: False  # noqa: E731

    directory = os.path.join(config.IMAGE_PATH, image_type)
    try:
        listing = {entry.name for entry in os.scandir(directory) if entry.is_file()}
    except (FileNotFoundError, NotADirectoryError, PermissionError, OSError):
        listing = set()

    try:
        from flask import g, has_request_context
        if has_request_context():
            setattr(g, cache_attr, listing)
    except Exception:
        pass

    return listing


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

    # Pass 32.9: decode inside a context manager and copy pixels off the
    # source handle before the upscale / downscale branches. A raising
    # upscale path otherwise leaks the file descriptor — exhausts the FD
    # table on bulk jobs of 10k boxart. Also sidesteps the Windows file
    # lock when _save_image() rewrites the same path.
    try:
        with Image.open(path) as src:
            src.load()
            img = src.copy()
    except Image.DecompressionBombError as e:
        logger.warning(f"Image standardize: decompression bomb rejected for {path} ({e})")
        return
    except Exception as e:
        logger.warning(f"Image standardize: cannot open {path}: {e}")
        return

    try:
        # For controllers/hardware, crop excess transparent space first.
        # crop() returns a NEW image; close the source copy so a bulk job of
        # 10k boxart doesn't leak one file descriptor per cropped/resized image
        # (the Pass 32.9 FD-exhaustion regression — only the final img was
        # closed in `finally`, every intermediate reassignment leaked).
        if image_type in ('controllers', 'hardware') and img.mode == 'RGBA':
            bbox = img.getbbox()
            if bbox:
                cropped = img.crop(bbox)
                img.close()
                img = cropped

        # Determine current relevant dimension
        w, h = img.size
        if image_type in ('controllers', 'hardware'):
            current = max(w, h)
        else:
            current = h

        # Check threshold band
        ratio = current / target
        if config.IMAGE_UPSCALE_THRESHOLD <= ratio <= config.IMAGE_DOWNSCALE_THRESHOLD:
            return

        # _upscale_image / _downscale_image always return a NEW PIL image and
        # never close their input, so close the source copy after reassigning.
        if ratio < config.IMAGE_UPSCALE_THRESHOLD:
            resized = _upscale_image(img, image_type, target, preserve_rgba)
        else:
            resized = _downscale_image(img, image_type, target)
        if resized is not img:
            img.close()
        img = resized

        if img is not None:
            _save_image(img, path)
    finally:
        try:
            if img is not None:
                img.close()
        except Exception:
            pass


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


def _atomic_save(img, path, fmt, **save_kwargs):
    """Pass 32.9 / 45.5 — save `img` to `path` atomically.

    Writes to a temp file in the same directory, fsyncs the file *and* the
    parent directory, and swaps into place with os.replace. A mid-write
    OOM / I/O error / client-disconnect can no longer leave a truncated
    file at `path`; a power loss after the rename can no longer lose the
    directory entry on XFS or `nobarrier` mounts.
    """
    dirname = os.path.dirname(path) or '.'
    os.makedirs(dirname, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.save_', dir=dirname)
    os.close(fd)
    try:
        img.save(tmp_path, fmt, **save_kwargs)
        # Pass 45.5 — the docstring claimed fsync but the previous version
        # never actually called it. PIL's img.save closes the underlying
        # file but doesn't fsync; without the explicit fsync below, a
        # power loss between PIL's close and os.replace lands a 0-byte or
        # partially-flushed file at the final path on next mount.
        sync_fd = os.open(tmp_path, os.O_RDONLY)
        try:
            os.fsync(sync_fd)
        except OSError:
            pass
        finally:
            os.close(sync_fd)
        os.replace(tmp_path, path)
        tmp_path = None
        # Fsync the directory so the rename is durable on next mount.
        try:
            from services.atomic_io import fsync_path
            fsync_path(dirname)
        except OSError:
            pass
    except Exception:
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        raise


def _save_image(img, path):
    """Save image preserving format with appropriate quality settings."""
    ext = os.path.splitext(path)[1].lower()

    # GIFs: never re-encode. PIL's `img.save(path, 'GIF')` without save_all
    # flattens animated GIFs to first frame, and any prior resize step has
    # already discarded subsequent frames. The original file on disk still
    # has the animation intact, so the safe path is to leave it untouched.
    if ext == '.gif':
        return

    try:
        if ext == '.webp':
            if img.mode == 'RGBA':
                _atomic_save(img, path, 'WEBP', quality=85, lossless=False)
            else:
                _atomic_save(img, path, 'WEBP', quality=85)
        elif ext in ('.jpg', '.jpeg'):
            if img.mode == 'RGBA':
                img = img.convert('RGB')
            _atomic_save(img, path, 'JPEG', quality=90)
        elif ext == '.png':
            _atomic_save(img, path, 'PNG')
        else:
            # Unknown format — save as PNG
            _atomic_save(img, path, 'PNG')
    except Exception as e:
        logger.error(f"Image standardize: failed to save {path}: {e}")
