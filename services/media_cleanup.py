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
# Built at call time (not module import) so it tracks the live config paths —
# matches how find_orphaned_media derives its media_dirs.
def _media_layout():
    return (
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
    # Pass 48.5 — boxart-family fields carry responsive `-sm`/`-md` siblings
    # (written by image_utils._make_responsive_variants) that the DB never
    # references. Unlink them alongside the primary so they don't strand on
    # disk until the next orphan sweep. Lazy import keeps the heavier image
    # stack out of the orphan-detection-only code path.
    from services.image_utils import _RESPONSIVE_VARIANTS, _variant_path

    deleted = 0

    for game in games:
        keys = game.keys() if hasattr(game, 'keys') else game
        for field, root_dir, container_prefix, is_list in _media_layout():
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
                if resolved and field in _RESPONSIVE_VARIANTS:
                    for suffix, _w in _RESPONSIVE_VARIANTS[field]:
                        if _try_remove(_variant_path(resolved, suffix), field):
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

    Pass 45.7 — each orphan dict carries the mtime observed at scan time AND
    the scan-start timestamp. ``clean_orphaned_files`` later checks both:
    if the file's current mtime is newer than the scan-start time, a scraper
    has touched it between scan and delete (race) and we skip the unlink.
    Also skips symlinks at scan time so a symlinked entry inside the media
    dirs (rare but possible from manual admin work) can never be unlinked
    by the cleaner.
    """
    import time as _time

    game_ids = {g['id'] for g in games}
    referenced_files = _collect_referenced_files(games)

    # Pass 48.4 — each entry carries the base its rel_path is computed
    # against, instead of inferring it from a ``'static' in dir_path``
    # substring test. Image dirs resolve against the parent of IMAGE_PATH so
    # rel_path is ``images/<sub>/<file>`` (the form DB references use); the
    # video dir resolves against STATIC_PATH so rel_path is ``videos/<file>``.
    # In standalone (PyInstaller) builds STATIC_PATH and IMAGE_PATH diverge,
    # so the old substring inference produced a wrong, ``../``-laden relpath.
    image_base = os.path.dirname(config.IMAGE_PATH)
    media_dirs = (
        (os.path.join(config.IMAGE_PATH, 'boxart'),      'boxart',      image_base),
        (os.path.join(config.IMAGE_PATH, 'boxart_3d'),   'boxart_3d',   image_base),
        (os.path.join(config.IMAGE_PATH, 'screenshots'), 'screenshots', image_base),
        (os.path.join(config.IMAGE_PATH, 'fanart'),      'fanart',      image_base),
        (os.path.join(config.STATIC_PATH, 'videos'),     'video',       config.STATIC_PATH),
        # Manuals live under IMAGE_PATH/manuals (matches every scraper output
        # and _media_layout). Was STATIC_PATH/manuals, which never existed.
        (os.path.join(config.IMAGE_PATH, 'manuals'),     'manual',      image_base),
    )

    orphaned = []
    total_size = 0
    scan_started_at = _time.time()

    for dir_path, media_type, rel_base in media_dirs:
        if not os.path.exists(dir_path):
            continue

        for filename in os.listdir(dir_path):
            filepath = os.path.join(dir_path, filename)
            # Pass 45.7 — refuse to ever consider symlinks. ``os.remove``
            # on a symlink unlinks the link itself (not the target), so
            # the worst case is benign, but the orphan detector wasn't
            # designed for them and a symlinked subdirectory inside the
            # media tree would leak through ``os.path.isfile`` (which
            # follows the link).
            if os.path.islink(filepath):
                continue
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
                rel_path = os.path.relpath(filepath, rel_base)
                if filename in referenced_files or rel_path in referenced_files:
                    is_orphaned = False
                else:
                    # Pass 48.2 — match on basename, not a substring. A DB
                    # value may store a path (e.g. ``images/boxart/42.png``);
                    # comparing basenames keeps that protected without the old
                    # ``filename in ref`` test also sparing unrelated refs that
                    # merely contain the name as a substring (e.g. ``42.png``
                    # inside ``442.png`` or ``42.png.bak``).
                    for ref in referenced_files:
                        if os.path.basename(ref) == filename:
                            is_orphaned = False
                            break

            if is_orphaned:
                try:
                    stat = os.stat(filepath)
                    size = stat.st_size
                    mtime = stat.st_mtime
                except OSError:
                    continue
                total_size += size
                orphaned.append({
                    'path': filepath,
                    'filename': filename,
                    'type': media_type,
                    'size': size,
                    # Pass 45.7 — recheck fields used by clean_orphaned_files
                    # to defeat the snapshot-then-delete race. Both must be
                    # carried in the dict so the route's preview→clean
                    # sequence keeps working without an extra arg.
                    'mtime': mtime,
                    'scan_started_at': scan_started_at,
                })

    return orphaned, total_size


def clean_orphaned_files(files, scan_started_override=None):
    """Delete the given orphan file list. Returns (deleted, errors, freed_bytes).

    Pass 45.7 — at delete time we re-check three things to defeat the
    snapshot-then-delete race against concurrent scrapers:
      1. The file still exists (a peer cleaner / user-initiated delete
         may already have removed it).
      2. It's still NOT a symlink — defence in depth against admin
         tinkering between scan and clean.
      3. Its mtime is unchanged from scan time. A scraper that wrote
         to ``42_boxart.webp`` between scan and clean bumps the mtime;
         the file may now be referenced by a row that was inserted
         after the scan started.
    A skipped file is logged at info so admins can see the cleaner
    deferred work rather than silently doing nothing.

    Pass 48.4 — ``scan_started_override`` lets the /clean route pass the
    *original preview* scan-start time. That route re-scans before deleting
    (so the file SET stays server-derived and trustworthy), but a fresh scan
    stamps each dict with a NEW scan-start, which would erase the preview→
    clean window the 45.7 defense was built for. With the override set we
    instead skip any candidate modified since the preview — a file a scraper
    wrote during the review window whose DB row may not have committed yet.
    A bogus override can only make the cleaner MORE conservative (or behave
    normally); it can never cause a referenced file to be deleted because the
    candidate set is still the server's own re-scan.
    """
    deleted = 0
    errors = 0
    skipped = 0
    freed_size = 0

    for file_info in files:
        filepath = file_info['path']
        try:
            if not os.path.exists(filepath):
                continue
            if os.path.islink(filepath):
                logger.info(
                    f"Skipping orphan candidate (symlink appeared after scan): {filepath}"
                )
                skipped += 1
                continue
            stat = os.stat(filepath)
            scan_mtime = file_info.get('mtime')
            scan_started_at = file_info.get('scan_started_at')
            if scan_started_override is not None:
                # Pass 48.4 — gate on the original preview time directly. The
                # per-file mtime/scan_started_at were captured by the /clean
                # re-scan (≈now), so they can't see the preview→clean window;
                # the preview timestamp can.
                if stat.st_mtime > scan_started_override:
                    logger.info(
                        f"Skipping orphan candidate (modified since preview): {filepath}"
                    )
                    skipped += 1
                    continue
            # If scan_started_at is unset (older callers), fall back to
            # the strict mtime-equality check; if BOTH are unset, behave
            # as before.
            elif scan_mtime is not None and stat.st_mtime > scan_mtime:
                # File was modified after scan recorded its mtime.
                # If we also know when the scan started, only refuse to
                # delete if the modification happened *after* scan start
                # (a scraper wrote to it during the cleanup window).
                if scan_started_at is None or stat.st_mtime > scan_started_at:
                    logger.info(
                        f"Skipping orphan candidate (modified during cleanup window): {filepath}"
                    )
                    skipped += 1
                    continue
            freed_size += stat.st_size
            os.remove(filepath)
            deleted += 1
            logger.info(f"Deleted orphaned file: {filepath}")
        except Exception as e:
            errors += 1
            logger.warning(f"Failed to delete orphaned file {filepath}: {e}")

    if skipped:
        logger.info(f"Orphan cleanup: skipped {skipped} files modified during the cleanup window")
    return deleted, errors, freed_size
