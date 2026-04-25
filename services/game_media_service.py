# =============================================================================
# RETRODB - Game Media Service
# =============================================================================
# File upload / removal / path resolution helpers for the manual game-edit
# flow. Extracted from routes/games.py so the POST /game/<id> handler can read
# as high-level business logic rather than ~100 lines of inline filesystem
# manipulation.
# =============================================================================

import io
import logging
import os
import tempfile

import config
from services.security import safe_path

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_EXT = frozenset({'jpg', 'jpeg', 'png', 'gif', 'webp'})
ALLOWED_VIDEO_EXT = frozenset({'mp4', 'webm', 'ogg'})

# Per-type upload size ceilings (bytes). Sit under the global
# MAX_CONTENT_LENGTH (16 MB) to reject oversize single files before they
# clobber disk. Videos stay at the global cap.
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB

# Matches video extensions but is checked by extension on the caller; we
# don't probe video containers here.
_VIDEO_EXT = ALLOWED_VIDEO_EXT


def _validate_image_bytes(raw: bytes) -> bool:
    """Decode the uploaded bytes with Pillow and run verify() to catch
    content-type spoofs (e.g. .exe renamed to .jpg). Returns True if the
    bytes parse as a real image, False otherwise. Pillow is a hard runtime
    dependency already (used for screenshot dedup + standardization).
    """
    try:
        from PIL import Image
    except ImportError:
        # Pillow missing → skip the magic-byte check rather than blocking
        # uploads entirely. In practice Pillow is always installed.
        logger.warning("Pillow not installed — skipping image magic-byte validation")
        return True
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.verify()
        return True
    except Exception as e:
        logger.warning(f"Image upload rejected by PIL.verify(): {e}")
        return False


def image_dir(subdir):
    """Absolute path to a per-type image subdirectory (boxart, fanart, ...)."""
    return os.path.join(config.IMAGE_PATH, subdir)


def resolve_media_path(filename, media_type):
    """Return the on-disk path for a stored media filename.

    Accepts bare filenames (e.g. "42_boxart.jpg"), STATIC-prefixed paths
    (e.g. "images/boxart/42_boxart.jpg"), and "videos/"-prefixed video paths.

    Pass 32.11: the returned path is always validated to live inside
    `config.STATIC_PATH` (via services.security.safe_path). A scraper
    filename derived from a URL could otherwise contain `../...`, letting
    `remove_media_file` delete files outside the image root. Returns None
    if the resolved path escapes STATIC_PATH.
    """
    if not filename:
        return None

    if media_type == 'video':
        if not filename.startswith('/') and not filename.startswith('videos/'):
            candidate = os.path.join(config.STATIC_PATH, 'videos', filename)
        else:
            candidate = os.path.join(config.STATIC_PATH, filename.lstrip('/'))
    else:
        subdir = media_type  # boxart, boxart_3d, fanart
        if not filename.startswith('/') and not filename.startswith('images/'):
            candidate = os.path.join(config.IMAGE_PATH, subdir, filename)
        else:
            candidate = os.path.join(config.STATIC_PATH, filename.lstrip('/'))

    safe = safe_path(candidate, config.STATIC_PATH)
    if safe is None:
        logger.warning(
            f"resolve_media_path rejected: {filename!r} (media_type={media_type}) "
            f"escapes STATIC_PATH"
        )
        return None
    return safe


def remove_media_file(filename, media_type):
    """Delete a stored media file from disk; log-and-swallow OS errors."""
    if not filename:
        return
    path = resolve_media_path(filename, media_type)
    if not path or not os.path.exists(path):
        return
    try:
        os.remove(path)
    except OSError as e:
        logger.warning(f"Could not delete {media_type} {path}: {e}")


def save_upload(file_storage, dest_dir, game_id, prefix, allowed_ext):
    """Persist an uploaded werkzeug FileStorage if present and valid.

    Validates extension, per-type size ceiling (MAX_IMAGE_SIZE for image
    uploads), and — for images — the magic bytes via Pillow so a renamed
    .exe in a .jpg file gets rejected before it hits disk.

    Args:
        file_storage: werkzeug FileStorage (from request.files.get(...)).
        dest_dir: absolute destination directory.
        game_id: game row id, used to namespace the output filename.
        prefix: filename discriminator (e.g. 'custom', 'custom_3d').
        allowed_ext: iterable of allowed lowercase extensions (no dots).

    Returns:
        str or None: saved filename (basename) on success, else None.
    """
    if not file_storage or not file_storage.filename:
        return None
    original = file_storage.filename
    ext = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
    if ext not in allowed_ext:
        logger.warning(f"Upload rejected: {original} — extension '{ext}' not allowed")
        return None

    is_image = ext in ALLOWED_IMAGE_EXT
    if is_image:
        raw = file_storage.read()
        if len(raw) > MAX_IMAGE_SIZE:
            logger.warning(f"Upload rejected: {original} — {len(raw)} bytes exceeds {MAX_IMAGE_SIZE}")
            return None
        if not _validate_image_bytes(raw):
            return None
        os.makedirs(dest_dir, exist_ok=True)
        new_filename = f"{game_id}_{prefix}.{ext}"
        # Pass 32.9: write via tmp + os.replace. On a mid-write OOM or I/O
        # error the destination path never exists in a truncated state.
        _atomic_write_bytes(os.path.join(dest_dir, new_filename), raw)
    else:
        # Video branch — Pass 25.6. Reject oversize videos before
        # file_storage.save() writes them to disk. Prefer Content-Length
        # when present (avoids buffering the whole payload), fall back to
        # a streamed read with a byte budget so multipart bodies without
        # per-part Content-Length are still bounded.
        # Pass 32.9: stream to a tempfile next to the destination, then
        # os.replace. Mid-stream abort removes the tmp and never leaves a
        # truncated artifact at `dest`.
        max_video_size = getattr(config, 'MAX_VIDEO_SIZE', 50 * 1024 * 1024)
        declared = getattr(file_storage, 'content_length', 0) or 0
        if declared and declared > max_video_size:
            logger.warning(
                f"Video upload rejected: {original} — declared "
                f"{declared} bytes exceeds {max_video_size}"
            )
            return None
        os.makedirs(dest_dir, exist_ok=True)
        new_filename = f"{game_id}_{prefix}.{ext}"
        dest = os.path.join(dest_dir, new_filename)
        fd, tmp_path = tempfile.mkstemp(prefix='.upload_', dir=dest_dir)
        try:
            with os.fdopen(fd, 'wb') as out:
                remaining = max_video_size
                while True:
                    chunk = file_storage.stream.read(min(1024 * 1024, remaining + 1))
                    if not chunk:
                        break
                    if len(chunk) > remaining:
                        logger.warning(
                            f"Video upload rejected: {original} — streaming size "
                            f"exceeded {max_video_size} bytes"
                        )
                        out.close()
                        try:
                            os.remove(tmp_path)
                        except OSError:
                            pass
                        return None
                    out.write(chunk)
                    remaining -= len(chunk)
            os.replace(tmp_path, dest)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise
    logger.info(f"Saved upload: {new_filename} to {dest_dir}")
    return new_filename


def _atomic_write_bytes(path, raw):
    """Write `raw` bytes to `path` atomically.

    Pass 45.5 — delegates to :func:`services.atomic_io.atomic_write_bytes`
    so the fsync + chmod-before-replace + parent-directory fsync sequence
    is shared across every atomic-write site in the codebase.
    """
    from services.atomic_io import atomic_write_bytes
    atomic_write_bytes(path, raw)


def save_screenshots(file_storages, game_id, existing_csv):
    """Append uploaded screenshots to the existing CSV list, skipping invalid
    extensions. Indexing continues from where the existing list left off.

    Returns the new comma-separated filename list (including prior entries).
    """
    existing = [s.strip() for s in (existing_csv or '').split(',') if s.strip()]
    valid = [f for f in (file_storages or []) if f and f.filename]
    if not valid:
        return ','.join(existing)

    ss_dir = image_dir('screenshots')
    os.makedirs(ss_dir, exist_ok=True)
    next_idx = len(existing) + 1
    for f in valid:
        original = f.filename
        ext = original.rsplit('.', 1)[-1].lower() if '.' in original else ''
        if ext not in ALLOWED_IMAGE_EXT:
            continue
        raw = f.read()
        if len(raw) > MAX_IMAGE_SIZE:
            logger.warning(f"Screenshot rejected: {original} — {len(raw)} bytes exceeds {MAX_IMAGE_SIZE}")
            continue
        if not _validate_image_bytes(raw):
            continue
        ss_filename = f"{game_id}_ss{next_idx}.{ext}"
        # Pass 32.9: atomic write so a mid-save failure never leaves a
        # truncated screenshot visible at its final path.
        _atomic_write_bytes(os.path.join(ss_dir, ss_filename), raw)
        existing.append(ss_filename)
        next_idx += 1
        logger.info(f"Saved screenshot: {ss_filename}")
    return ','.join(existing)


def try_standardize(path, media_type):
    """Run the full post-download pipeline (format-matches-extension check,
    size standardization, responsive variants). Pass 32.10 — what was
    `standardize_downloaded_image` alone now goes through
    `finalize_downloaded_image` so admin-uploaded PNG bytes inside a
    `.webp` file get re-encoded to real WebP before they persist.
    """
    try:
        from services.image_utils import finalize_downloaded_image
        finalize_downloaded_image(path, media_type)
    except Exception as e:
        logger.warning(f"Auto-resize {media_type} failed: {e}")
