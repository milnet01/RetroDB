# =============================================================================
# RETRODB - Game Media Service
# =============================================================================
# File upload / removal / path resolution helpers for the manual game-edit
# flow. Extracted from routes/games.py so the POST /game/<id> handler can read
# as high-level business logic rather than ~100 lines of inline filesystem
# manipulation.
# =============================================================================

import logging
import os

import config

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_EXT = frozenset({'jpg', 'jpeg', 'png', 'gif', 'webp'})
ALLOWED_VIDEO_EXT = frozenset({'mp4', 'webm', 'ogg'})


def image_dir(subdir):
    """Absolute path to a per-type image subdirectory (boxart, fanart, ...)."""
    return os.path.join(config.IMAGE_PATH, subdir)


def resolve_media_path(filename, media_type):
    """Return the on-disk path for a stored media filename.

    Accepts bare filenames (e.g. "42_boxart.jpg"), STATIC-prefixed paths
    (e.g. "images/boxart/42_boxart.jpg"), and "videos/"-prefixed video paths.
    """
    if media_type == 'video':
        if not filename.startswith('/') and not filename.startswith('videos/'):
            return os.path.join(config.STATIC_PATH, 'videos', filename)
        return os.path.join(config.STATIC_PATH, filename.lstrip('/'))

    subdir = media_type  # boxart, boxart_3d, fanart
    if not filename.startswith('/') and not filename.startswith('images/'):
        return os.path.join(config.IMAGE_PATH, subdir, filename)
    return os.path.join(config.STATIC_PATH, filename.lstrip('/'))


def remove_media_file(filename, media_type):
    """Delete a stored media file from disk; log-and-swallow OS errors."""
    if not filename:
        return
    path = resolve_media_path(filename, media_type)
    if not os.path.exists(path):
        return
    try:
        os.remove(path)
    except OSError as e:
        logger.warning(f"Could not delete {media_type} {path}: {e}")


def save_upload(file_storage, dest_dir, game_id, prefix, allowed_ext):
    """Persist an uploaded werkzeug FileStorage if present and valid.

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
    os.makedirs(dest_dir, exist_ok=True)
    new_filename = f"{game_id}_{prefix}.{ext}"
    file_storage.save(os.path.join(dest_dir, new_filename))
    logger.info(f"Saved upload: {new_filename} to {dest_dir}")
    return new_filename


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
        ss_filename = f"{game_id}_ss{next_idx}.{ext}"
        f.save(os.path.join(ss_dir, ss_filename))
        existing.append(ss_filename)
        next_idx += 1
        logger.info(f"Saved screenshot: {ss_filename}")
    return ','.join(existing)


def try_standardize(path, media_type):
    """Run the optional image-standardizer pass; warn-and-continue on failure."""
    try:
        from services.image_utils import standardize_downloaded_image
        standardize_downloaded_image(path, media_type)
    except Exception as e:
        logger.warning(f"Auto-resize {media_type} failed: {e}")
