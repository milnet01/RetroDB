# =============================================================================
# IMAGE DEDUPLICATION
# =============================================================================
# Perceptual-hash (dHash) helpers shared by every per-source scraper
# (`scraper/metadata_merger.py::apply_*_to_metadata`) to avoid appending
# visually-identical screenshots that have been scraped from more than one
# source.
#
# The 64-bit difference hash is tolerant of re-encoding / resize differences
# but not tolerant of crops or real gameplay variation, so threshold=10 has
# empirically worked well across sources (TGDB, IGDB, RAWG, ScreenScraper).
# =============================================================================

import os
import logging

from PIL import Image

from config import IMAGE_PATH

logger = logging.getLogger(__name__)


def compute_dhash(image_path, hash_size=8):
    """Compute a difference hash (dHash) for an image.

    Returns a 64-bit integer (for hash_size=8) or None on error.
    """
    try:
        img = Image.open(image_path).convert('L').resize(
            (hash_size + 1, hash_size), Image.LANCZOS
        )
        try:
            pixels = list(img.getdata())
            diff = 0
            for row in range(hash_size):
                for col in range(hash_size):
                    offset = row * (hash_size + 1) + col
                    if pixels[offset] > pixels[offset + 1]:
                        diff |= 1 << (row * hash_size + col)
            return diff
        finally:
            img.close()
    except (OSError, ValueError, Image.DecompressionBombError):
        # Pass 41.14.A — DecompressionBombError is a separate exception
        # (not a subclass of OSError/ValueError) raised by PIL when an
        # image's decoded pixel count exceeds Image.MAX_IMAGE_PIXELS. A
        # single bomb-image in a scraped screenshot batch would otherwise
        # propagate out of compute_dhash and abort the dedup loop for the
        # whole game.
        return None


def get_existing_screenshot_hashes(filenames):
    """Compute dHash for each filename under IMAGE_PATH/screenshots.

    Returns a list of (filename, hash_int) tuples, skipping any file that
    failed to hash (missing, corrupt, unreadable).
    """
    hashes = []
    for fname in filenames:
        path = os.path.join(IMAGE_PATH, 'screenshots', fname)
        h = compute_dhash(path)
        if h is not None:
            hashes.append((fname, h))
    return hashes


def is_visual_duplicate(new_path, existing_hashes, threshold=10):
    """Check whether `new_path` is a visual duplicate of any existing hash.

    Returns (True, matching_filename) or (False, None). The Hamming distance
    between two 64-bit dHashes typically sits around 0-3 for identical
    images, 10-20 for similar-but-different, and 25+ for unrelated.
    """
    new_hash = compute_dhash(new_path)
    if new_hash is None:
        return False, None
    for fname, h in existing_hashes:
        distance = bin(new_hash ^ h).count('1')
        if distance <= threshold:
            return True, fname
    return False, None


def keep_screenshot_if_unique(local_path, filename, existing_hashes, source_label=''):
    """Post-download dedup check.

    If `local_path` is a visual duplicate of an entry in `existing_hashes`:
    delete the file and return False. Otherwise: append the new (filename,
    hash) pair to `existing_hashes` and return True.

    `source_label` is used only in the "skipping duplicate" log message.
    """
    is_dup, match = is_visual_duplicate(local_path, existing_hashes)
    if is_dup:
        prefix = f"{source_label} " if source_label else ""
        logger.info(f"Skipping duplicate {prefix}screenshot {filename} (visually matches {match})")
        try:
            os.remove(local_path)
        except OSError:
            pass
        return False
    existing_hashes.append((filename, compute_dhash(local_path)))
    return True
