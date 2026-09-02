# =============================================================================
# RETRODB - Image Resize / Standardization Job
# =============================================================================
# Background job for bulk image standardization across all image directories.
# Follows MuseumGenerateJob pattern (threading, status dict, cancel support).
# =============================================================================

import os
import threading
import logging
import time
from datetime import datetime, timezone

from services.jobs.base import (
    persist_job_start,
    persist_job_progress,
    persist_job_complete,
    resolve_terminal_status,
    acquire_job_singleton_lock,
    release_singleton_fd,
)

logger = logging.getLogger(__name__)


class ImageResizeJob:
    """Manages bulk image standardization via Real-ESRGAN upscaling and Lanczos downscaling."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
        self._singleton_fd = None
        self.reset()

    def reset(self):
        """Reset job state."""
        self.running = False
        self.cancelled = False
        self.completed = False
        self.current_index = 0
        self.total_images = 0
        self.current_file = ""
        self.current_type = ""
        self.processed_count = 0
        self.skipped_count = 0
        self.upscaled_count = 0
        self.downscaled_count = 0
        self.failed_count = 0
        self.start_time = None
        self.end_time = None
        self.error_message = None
        self.persist_id = None

    def start(self, image_types=None):
        """Start bulk image standardization.

        Args:
            image_types: Optional list of types to process.
                         Defaults to ['boxart', 'screenshots', 'boxart_3d', 'controllers'].
        Returns:
            dict with status info.
        """
        with self._lock:
            if self.running:
                return {'success': False, 'error': 'Image resize already in progress'}

            singleton_fd = acquire_job_singleton_lock('image_resize')
            if singleton_fd is None:
                return {
                    'success': False,
                    'error': 'Image resize is already running on another worker process.',
                }

            self.reset()
            self._singleton_fd = singleton_fd
            self.running = True
            self.start_time = datetime.now(timezone.utc).isoformat()

            if image_types is None:
                image_types = ['boxart', 'screenshots', 'boxart_3d', 'controllers', 'hardware']

            self._thread = threading.Thread(
                target=self._worker,
                args=(image_types,),
                daemon=True
            )
            self._thread.start()

        return {'success': True, 'message': 'Image standardization started'}

    def cancel(self):
        """Cancel running job."""
        with self._lock:
            if not self.running:
                return {'success': False, 'error': 'No job running'}
            self.cancelled = True
        return {'success': True, 'message': 'Cancellation requested'}

    def get_status(self):
        """Return current job status.

        Pass 40.9 — read every shared counter under self._lock so a status
        poll racing with the worker thread can't see torn writes.
        """
        with self._lock:
            running = self.running
            cancelled = self.cancelled
            completed = self.completed
            current_index = self.current_index
            total_images = self.total_images
            current_file = self.current_file
            current_type = self.current_type
            processed_count = self.processed_count
            skipped_count = self.skipped_count
            upscaled_count = self.upscaled_count
            downscaled_count = self.downscaled_count
            failed_count = self.failed_count
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
            'total': total_images,
            'current_file': current_file,
            'current_type': current_type,
            'processed': processed_count,
            'skipped': skipped_count,
            'upscaled': upscaled_count,
            'downscaled': downscaled_count,
            'failed': failed_count,
            'percent': round(current_index / total_images * 100) if total_images else 0,
            'start_time': start_time,
            'end_time': end_time,
            'elapsed': elapsed,
            'error_message': error_message,
        }

    def _worker(self, image_types):
        """Background worker — scans directories and standardizes images.

        Pass 40.9 — full base.py convention:
          * persist_job_start before the loop, persist_job_progress every
            10 items / 30 s, persist_job_complete in finally
          * every read/write of self.* counters is under self._lock
          * resolve_terminal_status decides 'completed' vs 'cancelled'
        Without this, a SIGTERM mid-bulk-resize loses up to 10000 items'
        worth of progress and leaves no audit trail.
        """
        import config

        SUPPORTED_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

        persist_id = None
        last_persist_time = time.time()
        try:
            persist_id = persist_job_start('image_resize', {
                'image_types': list(image_types),
            })
            with self._lock:
                self.persist_id = persist_id

            # Build file list
            from services.image_utils import _RESPONSIVE_VARIANTS

            files_to_process = []
            for img_type in image_types:
                if img_type in config.IMAGE_SKIP_TYPES:
                    continue

                dir_path = os.path.join(config.IMAGE_PATH, img_type)
                if not os.path.isdir(dir_path):
                    continue

                if img_type in ('controllers', 'hardware'):
                    target = config.IMAGE_TARGET_LONGEST_EDGE
                    preserve_rgba = True
                else:
                    target = config.IMAGE_TARGET_HEIGHT
                    preserve_rgba = img_type == 'boxart_3d'  # 3D boxart often has transparency

                # Skip the responsive variants this job's own output creates.
                # They live beside the primary and the listing matched on
                # extension alone, so a 160px `-sm` scored far under the
                # upscale threshold, was blown up to full height, and then had
                # variants generated FROM it -- `foo-sm-sm.jpg`, `foo-sm-md.jpg`
                # -- which the next run upscaled in turn. Three costs: srcset
                # served a full-size image under the `-sm` name (killing the
                # payload saving), Real-ESRGAN ran on ~3x the intended files,
                # and every run multiplied the file count. Suffixes come from
                # _RESPONSIVE_VARIANTS itself so the two cannot drift.
                variant_suffixes = tuple(
                    f"-{suffix}" for suffix, _ in _RESPONSIVE_VARIANTS.get(img_type, ())
                )

                for fname in os.listdir(dir_path):
                    stem, ext = os.path.splitext(fname)
                    ext = ext.lower()
                    if ext in SUPPORTED_EXTS:
                        if variant_suffixes and stem.endswith(variant_suffixes):
                            continue
                        files_to_process.append({
                            'path': os.path.join(dir_path, fname),
                            'type': img_type,
                            'name': fname,
                            'target': target,
                            'preserve_rgba': preserve_rgba,
                        })

            with self._lock:
                self.total_images = len(files_to_process)
                total = self.total_images

            if total == 0:
                logger.info("Image resize: no images found to process")
                return

            # Log per-type counts
            type_counts = {}
            for item in files_to_process:
                type_counts[item['type']] = type_counts.get(item['type'], 0) + 1
            for t, c in type_counts.items():
                logger.info(f"Image resize: {c} {t} images queued")

            current_type_name = None
            for i, item in enumerate(files_to_process):
                with self._lock:
                    if self.cancelled:
                        break

                with self._lock:
                    self.current_index = i + 1
                    self.current_file = item['name']
                    self.current_type = item['type']

                # Log when switching image types
                if item['type'] != current_type_name:
                    current_type_name = item['type']
                    logger.info(f"Image resize: starting {current_type_name} images...")

                # Persist progress every 10 items or 30 seconds.
                _now = time.time()
                if persist_id and ((i % 10 == 0 or _now - last_persist_time >= 30) and i > 0):
                    with self._lock:
                        _progress = {
                            'current': i,
                            'total': self.total_images,
                            'processed': self.processed_count,
                            'skipped': self.skipped_count,
                            'failed': self.failed_count,
                            'upscaled': self.upscaled_count,
                            'downscaled': self.downscaled_count,
                            'current_item': item['name'],
                        }
                    persist_job_progress(persist_id, _progress)
                    last_persist_time = _now

                try:
                    result = _standardize_with_tracking(
                        item['path'], item['type'], item['target'], item['preserve_rgba']
                    )
                    with self._lock:
                        if result == 'skipped':
                            self.skipped_count += 1
                        elif result == 'upscaled':
                            self.upscaled_count += 1
                            self.processed_count += 1
                        elif result == 'downscaled':
                            self.downscaled_count += 1
                            self.processed_count += 1
                        else:
                            self.skipped_count += 1
                except Exception as e:
                    logger.error(f"Image resize: failed on {item['type']}/{item['name']}: {e}", exc_info=True)
                    with self._lock:
                        self.failed_count += 1

        except Exception as e:
            logger.error(f"Image resize worker error: {e}")
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
                    self.processed_count, self.skipped_count, self.failed_count,
                    self.upscaled_count, self.downscaled_count,
                )
            release_singleton_fd(self)
            if persist_id:
                persist_job_complete(persist_id, status=final_status)
            logger.info(
                f"Image resize complete: {snapshot[0]} processed, "
                f"{snapshot[1]} skipped, {snapshot[2]} failed "
                f"({snapshot[3]} upscaled, {snapshot[4]} downscaled)"
            )


def _standardize_with_tracking(path, image_type, target, preserve_rgba):
    """Standardize image and return action taken: 'skipped', 'upscaled', or 'downscaled'.

    Similar to standardize_image but returns a status string for tracking.
    """
    import config
    from PIL import Image
    from services.image_utils import _upscale_image, _downscale_image, _save_image

    if not os.path.isfile(path):
        logger.debug(f"Image resize: file no longer exists {path} (deleted by dedup?)")
        return 'skipped'

    # Pass 32.9: decode inside a context manager and copy pixels off the
    # source handle. The pre-existing flow leaked a file descriptor on any
    # raising path through _upscale_image — 10 000+ leaked FDs on a bulk
    # resize job exhausts the process's open-file limit.
    try:
        with Image.open(path) as src:
            src.load()
            img = src.copy()
    except Exception as e:
        logger.warning(f"Image resize: cannot open {path}: {e}")
        raise

    result_img = None
    try:
        # For controllers/hardware, crop excess transparent space first
        if image_type in ('controllers', 'hardware') and img.mode == 'RGBA':
            bbox = img.getbbox()
            if bbox:
                img = img.crop(bbox)

        w, h = img.size
        if image_type in ('controllers', 'hardware'):
            current = max(w, h)
        else:
            current = h

        ratio = current / target
        if config.IMAGE_UPSCALE_THRESHOLD <= ratio <= config.IMAGE_DOWNSCALE_THRESHOLD:
            return 'skipped'

        if ratio < config.IMAGE_UPSCALE_THRESHOLD:
            result_img = _upscale_image(img, image_type, target, preserve_rgba)
            action = 'upscaled'
        else:
            result_img = _downscale_image(img, image_type, target)
            action = 'downscaled'

        if result_img is not None:
            _save_image(result_img, path)
    finally:
        try:
            if result_img is not None and result_img is not img:
                result_img.close()
        except Exception:
            pass
        try:
            img.close()
        except Exception:
            pass

    # Regenerate responsive variants for boxart-family types so cards / hero
    # images pick up the new primary on the next page load.
    try:
        from services.image_utils import _make_responsive_variants
        _make_responsive_variants(path, image_type)
    except Exception as e:
        logger.warning(f"Responsive variant regen failed for {path}: {e}")

    return action
