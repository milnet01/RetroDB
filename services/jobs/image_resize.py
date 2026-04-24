# =============================================================================
# RETRODB - Image Resize / Standardization Job
# =============================================================================
# Background job for bulk image standardization across all image directories.
# Follows MuseumGenerateJob pattern (threading, status dict, cancel support).
# =============================================================================

import os
import threading
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class ImageResizeJob:
    """Manages bulk image standardization via Real-ESRGAN upscaling and Lanczos downscaling."""

    def __init__(self):
        self._lock = threading.Lock()
        self._thread = None
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

            self.reset()
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
        """Return current job status."""
        elapsed = None
        if self.start_time:
            try:
                start = datetime.fromisoformat(self.start_time)
                end = datetime.fromisoformat(self.end_time) if self.end_time else datetime.now(timezone.utc)
                elapsed = int((end - start).total_seconds())
            except (ValueError, TypeError):
                pass

        return {
            'running': self.running,
            'cancelled': self.cancelled,
            'completed': self.completed,
            'current': self.current_index,
            'total': self.total_images,
            'current_file': self.current_file,
            'current_type': self.current_type,
            'processed': self.processed_count,
            'skipped': self.skipped_count,
            'upscaled': self.upscaled_count,
            'downscaled': self.downscaled_count,
            'failed': self.failed_count,
            'percent': round(self.current_index / self.total_images * 100) if self.total_images else 0,
            'start_time': self.start_time,
            'end_time': self.end_time,
            'elapsed': elapsed,
            'error_message': self.error_message,
        }

    def _worker(self, image_types):
        """Background worker — scans directories and standardizes images."""
        import config
        from services.image_utils import standardize_image

        SUPPORTED_EXTS = {'.jpg', '.jpeg', '.png', '.webp', '.gif'}

        try:
            # Build file list
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

                for fname in os.listdir(dir_path):
                    ext = os.path.splitext(fname)[1].lower()
                    if ext in SUPPORTED_EXTS:
                        files_to_process.append({
                            'path': os.path.join(dir_path, fname),
                            'type': img_type,
                            'name': fname,
                            'target': target,
                            'preserve_rgba': preserve_rgba,
                        })

            self.total_images = len(files_to_process)

            if self.total_images == 0:
                logger.info("Image resize: no images found to process")
                self.running = False
                self.completed = True
                self.end_time = datetime.now(timezone.utc).isoformat()
                return

            # Log per-type counts
            type_counts = {}
            for item in files_to_process:
                type_counts[item['type']] = type_counts.get(item['type'], 0) + 1
            for t, c in type_counts.items():
                logger.info(f"Image resize: {c} {t} images queued")

            current_type_name = None
            for i, item in enumerate(files_to_process):
                if self.cancelled:
                    break

                self.current_index = i + 1
                self.current_file = item['name']
                self.current_type = item['type']

                # Log when switching image types
                if item['type'] != current_type_name:
                    current_type_name = item['type']
                    logger.info(f"Image resize: starting {current_type_name} images...")

                try:
                    result = _standardize_with_tracking(
                        item['path'], item['type'], item['target'], item['preserve_rgba']
                    )
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
                    self.failed_count += 1

        except Exception as e:
            logger.error(f"Image resize worker error: {e}")
            self.error_message = str(e)
        finally:
            self.running = False
            self.completed = True
            self.end_time = datetime.now(timezone.utc).isoformat()
            logger.info(
                f"Image resize complete: {self.processed_count} processed, "
                f"{self.skipped_count} skipped, {self.failed_count} failed "
                f"({self.upscaled_count} upscaled, {self.downscaled_count} downscaled)"
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
