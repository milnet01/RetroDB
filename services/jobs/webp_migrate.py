# =============================================================================
# RETRODB - Bulk JPEG/PNG → WebP Migration Job
# =============================================================================
# Walks games.boxart / boxart_3d / fanart / screenshots (comma-split) and
# rewrites each legacy `.jpg` / `.jpeg` / `.png` referenced file as a sibling
# `.webp`, updates the DB filename in-place, then deletes the original after
# verifying the new file opens. Manuals (PDFs) and pre-existing WebP / GIF
# files are skipped. Follows the ImageResizeJob pattern: threading, singleton
# lock, status/cancel API, base.persist_job_* progress checkpointing.
# =============================================================================

import os
import shutil
import threading
import logging
import time
from datetime import datetime, timezone

from services.jobs.base import (
    _get_conn,
    persist_job_start,
    persist_job_progress,
    persist_job_complete,
    resolve_terminal_status,
    acquire_job_singleton_lock,
    release_singleton_fd,
)

logger = logging.getLogger(__name__)


# Sources we walk and the on-disk subdirectory each maps to. `screenshots`
# is comma-split at query time; the others are single-valued.
_SOURCES = (
    ('boxart',      'boxart',      False),
    ('boxart_3d',   'boxart_3d',   False),
    ('fanart',      'fanart',      False),
    ('screenshots', 'screenshots', True),  # comma-split
)

# Extensions we rewrite. WebP / GIF / non-image extensions pass through. The
# spec calls out JPEG + PNG only — anything else (e.g. .bmp) is too rare to
# touch and might trip mode-conversion edge cases we haven't covered.
_CONVERTIBLE_EXTS = frozenset({'.jpg', '.jpeg', '.png'})


class WebPMigrateJob:
    """Bulk migration of legacy JPEG / PNG library files to WebP."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.reset()

    def reset(self):
        self.running = False
        self.cancelled = False
        self.completed = False
        self.current_index = 0
        self.total_files = 0
        self.current_file = ""
        self.current_type = ""
        self.converted_count = 0
        self.skipped_count = 0
        self.failed_count = 0
        self.bytes_saved = 0
        self.start_time = None
        self.end_time = None
        self.error_message = None
        self.persist_id = None

    def start(self):
        """Start the migration. Returns a dict with `success` + `message` / `error`."""
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'WebP migration already in progress'}

            singleton_fd = acquire_job_singleton_lock('webp_migrate')
            if singleton_fd is None:
                return {
                    'success': False,
                    'error': 'WebP migration is already running on another worker process.',
                }

            self.reset()
            self._singleton_fd = singleton_fd
            self.running = True
            self.start_time = datetime.now(timezone.utc).isoformat()

            self._thread = threading.Thread(target=self._worker, daemon=True)
            self._thread.start()

        return {'success': True, 'message': 'WebP migration started'}

    def cancel(self):
        with self._lock:
            if not self.running:
                return {'success': False, 'error': 'No job running'}
            self.cancelled = True
        return {'success': True, 'message': 'Cancellation requested'}

    def get_status(self):
        """Snapshot every shared counter under the lock to avoid torn reads."""
        with self._lock:
            running = self.running
            cancelled = self.cancelled
            completed = self.completed
            current_index = self.current_index
            total_files = self.total_files
            current_file = self.current_file
            current_type = self.current_type
            converted_count = self.converted_count
            skipped_count = self.skipped_count
            failed_count = self.failed_count
            bytes_saved = self.bytes_saved
            start_time = self.start_time
            end_time = self.end_time
            error_message = self.error_message

        elapsed = None
        if start_time:
            try:
                start = datetime.fromisoformat(start_time)
                end = datetime.fromisoformat(end_time) if end_time else datetime.now(timezone.utc)
                elapsed = int((end - start).total_seconds())
            except (ValueError, TypeError):
                pass

        return {
            'running': running,
            'cancelled': cancelled,
            'completed': completed,
            'current': current_index,
            'total': total_files,
            'current_file': current_file,
            'current_type': current_type,
            'converted': converted_count,
            'skipped': skipped_count,
            'failed': failed_count,
            'bytes_saved': bytes_saved,
            'percent': round(current_index / total_files * 100) if total_files else 0,
            'start_time': start_time,
            'end_time': end_time,
            'elapsed': elapsed,
            'error_message': error_message,
        }

    def _worker(self):
        import config

        persist_id = None
        last_persist_time = time.time()
        try:
            work_items, in_scope_bytes = _build_work_list()

            # Disk-space guard. WebP is normally smaller than JPEG, but a
            # cold cap of 2× the in-scope total protects against the worst
            # case (re-encoding loss + tmp files held during atomic save).
            try:
                free_bytes = shutil.disk_usage(config.IMAGE_PATH).free
            except (OSError, AttributeError):
                free_bytes = None
            if free_bytes is not None and free_bytes < 2 * in_scope_bytes:
                msg = (
                    f"Refusing to start: free disk {free_bytes / 1e6:.0f} MB "
                    f"< 2× in-scope media size ({in_scope_bytes / 1e6:.0f} MB). "
                    f"Free up space and retry."
                )
                logger.warning(msg)
                with self._lock:
                    self.error_message = msg
                return

            persist_id = persist_job_start('webp_migrate', {
                'total_files': len(work_items),
                'in_scope_bytes': in_scope_bytes,
            })
            with self._lock:
                self.persist_id = persist_id
                self.total_files = len(work_items)
                total = self.total_files

            if total == 0:
                logger.info("WebP migration: nothing to convert")
                return

            logger.info(f"WebP migration: {total} files queued ({in_scope_bytes / 1e6:.1f} MB)")

            for i, item in enumerate(work_items):
                with self._lock:
                    if self.cancelled:
                        break
                    self.current_index = i + 1
                    self.current_file = item['filename']
                    self.current_type = item['image_type']

                _now = time.time()
                if persist_id and ((i % 20 == 0 or _now - last_persist_time >= 30) and i > 0):
                    with self._lock:
                        _progress = {
                            'current': i,
                            'total': self.total_files,
                            'converted': self.converted_count,
                            'skipped': self.skipped_count,
                            'failed': self.failed_count,
                            'bytes_saved': self.bytes_saved,
                            'current_item': item['filename'],
                        }
                    persist_job_progress(persist_id, _progress)
                    last_persist_time = _now

                try:
                    result, saved = _migrate_one(item)
                    with self._lock:
                        if result == 'converted':
                            self.converted_count += 1
                            self.bytes_saved += saved
                        elif result == 'skipped':
                            self.skipped_count += 1
                        else:
                            self.failed_count += 1
                except Exception as e:
                    logger.error(
                        f"WebP migration: failed on {item['image_type']}/{item['filename']}: {e}",
                        exc_info=True,
                    )
                    with self._lock:
                        self.failed_count += 1

        except Exception as e:
            logger.error(f"WebP migration worker error: {e}")
            with self._lock:
                self.error_message = str(e)
            if persist_id:
                persist_job_complete(persist_id, status='failed', error=str(e))
                persist_id = None
        finally:
            with self._lock:
                self.running = False
                self.completed = True
                self.end_time = datetime.now(timezone.utc).isoformat()
                final_status = resolve_terminal_status(self.cancelled)
                snapshot = (
                    self.converted_count, self.skipped_count, self.failed_count,
                    self.bytes_saved,
                )
            release_singleton_fd(self)
            if persist_id:
                persist_job_complete(persist_id, status=final_status)
            logger.info(
                f"WebP migration complete: {snapshot[0]} converted, "
                f"{snapshot[1]} skipped, {snapshot[2]} failed "
                f"({snapshot[3] / 1e6:.1f} MB saved)"
            )


# ---------------------------------------------------------------------------
# Work-list builder + per-file migrator
# ---------------------------------------------------------------------------

def _build_work_list():
    """Walk games for media filenames worth converting.

    Returns `(items, in_scope_bytes)` where each `item` is a dict shaped:
        {
            'game_id': int,
            'column': 'boxart' | 'boxart_3d' | 'fanart' | 'screenshots',
            'image_type': matching subdir name,
            'is_csv': bool,
            'filename': str,    # the bare entry as it appears in the DB
        }
    Only files with a `.jpg` / `.jpeg` / `.png` extension are included; WebP
    / GIF / missing-on-disk entries are filtered out here so the worker
    loop is straight conversion.
    """
    import config

    items = []
    in_scope_bytes = 0

    conn = _get_conn()
    try:
        for column, image_subdir, is_csv in _SOURCES:
            # Column names are hard-coded in `_SOURCES`; no user input
            # reaches the f-string interpolation.
            rows = conn.execute(
                f"SELECT id, {column} AS val FROM games "
                f"WHERE {column} IS NOT NULL AND {column} != ''"
            ).fetchall()
            directory = os.path.join(config.IMAGE_PATH, image_subdir)
            for row in rows:
                raw = row['val'] or ''
                entries = [s.strip() for s in raw.split(',')] if is_csv else [raw.strip()]
                for entry in entries:
                    if not entry:
                        continue
                    ext = os.path.splitext(entry)[1].lower()
                    if ext not in _CONVERTIBLE_EXTS:
                        continue
                    full_path = os.path.join(directory, entry)
                    try:
                        size = os.path.getsize(full_path)
                    except OSError:
                        # Stale DB pointer — skip silently; image-resize / media-
                        # cleanup jobs are the right place to garbage-collect.
                        continue
                    items.append({
                        'game_id': row['id'],
                        'column': column,
                        'image_type': image_subdir,
                        'is_csv': is_csv,
                        'filename': entry,
                        'full_path': full_path,
                    })
                    in_scope_bytes += size
    finally:
        conn.close()

    return items, in_scope_bytes


def _migrate_one(item):
    """Convert one file. Returns `(status, bytes_saved)`.

    `status` is `'converted'` (success), `'skipped'` (target .webp already
    exists or original is gone), or `'failed'` (unrecoverable error). The
    DB column is updated once the new .webp opens cleanly; only then is
    the original deleted, so a mid-conversion crash leaves at worst an
    orphan .webp + intact original on disk.
    """
    import config
    from PIL import Image
    from services.image_utils import _save_image, _make_responsive_variants

    full_path = item['full_path']
    if not os.path.isfile(full_path):
        return ('skipped', 0)

    stem, ext = os.path.splitext(item['filename'])
    new_filename = f"{stem}.webp"
    directory = os.path.join(config.IMAGE_PATH, item['image_type'])
    new_full_path = os.path.join(directory, new_filename)

    # If the .webp already exists, treat that as a partial-migration
    # leftover: update the DB to point at it and remove the original
    # without re-encoding (saves a PIL round-trip and avoids overwriting
    # whatever variant is already there).
    if os.path.exists(new_full_path):
        original_size = os.path.getsize(full_path)
        if _update_db_filename(item, new_filename):
            try:
                os.remove(full_path)
            except OSError as e:
                logger.warning(f"WebP migration: could not delete original {full_path}: {e}")
            return ('converted', original_size)
        return ('failed', 0)

    original_size = os.path.getsize(full_path)

    try:
        with Image.open(full_path) as src:
            src.load()
            img = src.copy()
    except Exception as e:
        logger.warning(f"WebP migration: cannot open {full_path}: {e}")
        return ('failed', 0)

    try:
        _save_image(img, new_full_path)
    finally:
        try:
            img.close()
        except Exception:
            pass

    # Verify the new file opens cleanly — _save_image swallows its own
    # errors, so the only way to know the WebP is good is to re-read it.
    if not os.path.exists(new_full_path):
        logger.error(f"WebP migration: save reported no error but {new_full_path} is missing")
        return ('failed', 0)
    try:
        with Image.open(new_full_path) as verify:
            verify.verify()
    except Exception as e:
        logger.error(f"WebP migration: verification failed for {new_full_path}: {e}")
        try:
            os.remove(new_full_path)
        except OSError:
            pass
        return ('failed', 0)

    # DB update is the commit point — only after it lands do we delete the
    # original. If the UPDATE fails, the new .webp stays as an orphan
    # (cleanable via media-cleanup), but the DB still references a real
    # file.
    if not _update_db_filename(item, new_filename):
        try:
            os.remove(new_full_path)
        except OSError:
            pass
        return ('failed', 0)

    try:
        os.remove(full_path)
    except OSError as e:
        logger.warning(f"WebP migration: could not delete original {full_path}: {e}")

    # Clean up sibling responsive variants for the OLD extension; regenerate
    # them against the new .webp so card srcset stays in sync.
    if item['image_type'] in ('boxart', 'boxart_3d'):
        for suffix in ('sm', 'md'):
            for variant_ext in _CONVERTIBLE_EXTS:
                old_variant = os.path.join(directory, f"{stem}-{suffix}{variant_ext}")
                if os.path.exists(old_variant):
                    try:
                        os.remove(old_variant)
                    except OSError:
                        pass
        try:
            _make_responsive_variants(new_full_path, item['image_type'])
        except Exception as e:
            logger.warning(f"WebP migration: variant regen failed for {new_full_path}: {e}")

    new_size = 0
    try:
        new_size = os.path.getsize(new_full_path)
    except OSError:
        pass
    saved = max(0, original_size - new_size)
    return ('converted', saved)


def _update_db_filename(item, new_filename):
    """Swap `old_filename` for `new_filename` in the row's media column.

    Non-screenshots use a direct UPDATE keyed on the old value to avoid a
    race with a concurrent edit-modal save. Screenshots are CSV — read,
    split, exact-match replace, rejoin, then UPDATE keyed on the original
    CSV value for the same reason.

    Returns True if a row was actually updated, False if the row had
    already moved on (e.g. the edit modal swapped boxart between the
    work-list build and now).
    """
    old_filename = item['filename']
    game_id = item['game_id']
    column = item['column']

    conn = _get_conn()
    try:
        if not item['is_csv']:
            cur = conn.execute(
                f"UPDATE games SET {column} = ? WHERE id = ? AND {column} = ?",
                (new_filename, game_id, old_filename),
            )
            conn.commit()
            return cur.rowcount > 0

        # CSV path: read-modify-write under the same connection so the
        # UPDATE's `AND screenshots = ?` guard sees the row we just read.
        row = conn.execute(
            f"SELECT {column} AS val FROM games WHERE id = ?",
            (game_id,),
        ).fetchone()
        if not row or not row['val']:
            return False
        current_entries = [s.strip() for s in row['val'].split(',')]
        if old_filename not in current_entries:
            return False
        new_entries = [new_filename if e == old_filename else e for e in current_entries]
        new_value = ','.join(new_entries)
        cur = conn.execute(
            f"UPDATE games SET {column} = ? WHERE id = ? AND {column} = ?",
            (new_value, game_id, row['val']),
        )
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()
