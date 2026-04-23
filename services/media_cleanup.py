# =============================================================================
# RETRODB - Media cleanup
# =============================================================================
# Per-game media deletion + orphan detection for the media directories:
# boxart, boxart_3d, screenshots, fanart, video, manual.
# =============================================================================

import logging
import os

import config
from services.security import safe_path

logger = logging.getLogger(__name__)


# Per-field layout: (db_field, root_dir, container_prefix, is_list).
# `root_dir` is where files live on disk when the DB value is a bare filename.
# `container_prefix` is the top-level segment that indicates a stored value is
# already a relative-to-STATIC path (e.g. "images/boxart/foo.png"), in which
# case we join against STATIC_PATH instead.
_MEDIA_LAYOUT = (
    ('boxart',      os.path.join(config.IMAGE_PATH, 'boxart'),      'images/', False),
    ('boxart_3d',   os.path.join(config.IMAGE_PATH, 'boxart_3d'),   'images/', False),
    ('fanart',      os.path.join(config.IMAGE_PATH, 'fanart'),      'images/', False),
    ('screenshots', os.path.join(config.IMAGE_PATH, 'screenshots'), 'images/', True),
    ('video',       os.path.join(config.STATIC_PATH, 'videos'),     'videos/', False),
    ('manual',      os.path.join(config.IMAGE_PATH, 'manuals'),     'images/', False),
)


def _resolve_media_path(value, root_dir, container_prefix):
    """Resolve a DB media value to an absolute path inside STATIC_PATH, or None if unsafe."""
    if value.startswith('/') or value.startswith(container_prefix):
        path = os.path.join(config.STATIC_PATH, value.lstrip('/'))
    else:
        path = os.path.join(root_dir, value)
    return safe_path(path, config.STATIC_PATH)


def _try_remove(path, label):
    if not path or not os.path.exists(path):
        return False
    try:
        os.remove(path)
        return True
    except Exception as e:
        logger.warning(f"Could not delete {label} {path}: {e}")
        return False


def delete_game_images(games):
    """Delete image/media files for a list of game rows.

    `games` is an iterable of dict-like rows with boxart/boxart_3d/fanart/
    screenshots/video/manual columns. Returns the number of files removed.
    """
    deleted = 0

    for game in games:
        keys = game.keys() if hasattr(game, 'keys') else game
        for field, root_dir, container_prefix, is_list in _MEDIA_LAYOUT:
            if field not in keys:
                continue
            value = game[field]
            if not value:
                continue

            if is_list:
                for entry in value.split(','):
                    entry = entry.strip()
                    if not entry:
                        continue
                    resolved = _resolve_media_path(entry, root_dir, container_prefix)
                    if _try_remove(resolved, field):
                        deleted += 1
            else:
                resolved = _resolve_media_path(value, root_dir, container_prefix)
                if _try_remove(resolved, field):
                    deleted += 1

    return deleted


def _collect_referenced_files(games):
    referenced = set()
    for game in games:
        for field in ('boxart', 'boxart_3d', 'fanart', 'video', 'manual'):
            value = game[field]
            if value:
                referenced.add(value)
        if game['screenshots']:
            for ss in game['screenshots'].split(','):
                ss = ss.strip()
                if ss:
                    referenced.add(ss)
    return referenced


def find_orphaned_media(games):
    """Walk media directories and return (orphan_list, total_bytes).

    A file is considered orphaned if its "<game_id>_" filename prefix does not
    match any live game ID and its filename is not referenced by any games row.
    """
    game_ids = {g['id'] for g in games}
    referenced_files = _collect_referenced_files(games)

    media_dirs = (
        (os.path.join(config.IMAGE_PATH, 'boxart'),      'boxart'),
        (os.path.join(config.IMAGE_PATH, 'boxart_3d'),   'boxart_3d'),
        (os.path.join(config.IMAGE_PATH, 'screenshots'), 'screenshots'),
        (os.path.join(config.IMAGE_PATH, 'fanart'),      'fanart'),
        (os.path.join(config.STATIC_PATH, 'videos'),     'video'),
        # Manuals live under IMAGE_PATH/manuals (matches every scraper output
        # and _MEDIA_LAYOUT). Was STATIC_PATH/manuals, which never existed.
        (os.path.join(config.IMAGE_PATH, 'manuals'),     'manual'),
    )

    orphaned = []
    total_size = 0

    for dir_path, media_type in media_dirs:
        if not os.path.exists(dir_path):
            continue

        for filename in os.listdir(dir_path):
            filepath = os.path.join(dir_path, filename)
            if not os.path.isfile(filepath):
                continue

            is_orphaned = True

            try:
                file_prefix = filename.split('_')[0]
                if file_prefix.isdigit():
                    game_id = int(file_prefix)
                    if game_id in game_ids:
                        is_orphaned = False
            except (ValueError, IndexError):
                pass

            if is_orphaned:
                rel_path = os.path.relpath(
                    filepath,
                    config.STATIC_PATH if 'static' in dir_path else os.path.dirname(config.IMAGE_PATH),
                )
                if filename in referenced_files or rel_path in referenced_files:
                    is_orphaned = False
                else:
                    for ref in referenced_files:
                        if filename in ref:
                            is_orphaned = False
                            break

            if is_orphaned:
                size = os.path.getsize(filepath)
                total_size += size
                orphaned.append({
                    'path': filepath,
                    'filename': filename,
                    'type': media_type,
                    'size': size,
                })

    return orphaned, total_size


def clean_orphaned_files(files):
    """Delete the given orphan file list. Returns (deleted, errors, freed_bytes)."""
    deleted = 0
    errors = 0
    freed_size = 0

    for file_info in files:
        filepath = file_info['path']
        try:
            if os.path.exists(filepath):
                freed_size += os.path.getsize(filepath)
                os.remove(filepath)
                deleted += 1
                logger.info(f"Deleted orphaned file: {filepath}")
        except Exception as e:
            errors += 1
            logger.warning(f"Failed to delete orphaned file {filepath}: {e}")

    return deleted, errors, freed_size
