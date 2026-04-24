# =============================================================================
# RETRODB - Atomic File Write Helpers
# =============================================================================
# Crash-safe replacements for the plain `open('w') + json.dump` pattern.
# A power loss or kernel panic mid-write would otherwise truncate the target
# file, wiping configuration that lives in user-editable JSON (settings.json,
# scraper_settings.json, etc.).
# =============================================================================

import json
import os


def atomic_write_json(path, data, indent=2):
    """Write `data` as JSON to `path` atomically.

    Writes to a sibling tempfile, fsyncs, then `os.replace()` swaps it into
    place — `os.replace` is atomic on POSIX and Windows, so any reader sees
    either the old file or the new file, never a half-written one.

    Args:
        path: Destination file path.
        data: JSON-serializable object.
        indent: `json.dump` indent (default 2 to match existing style).

    Raises:
        OSError: if the directory is unwritable or the swap fails.
        TypeError: if `data` cannot be serialized.
    """
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
        # Pass 35.2 — os.replace is atomic but the directory entry update
        # isn't durable until the directory itself is fsynced. On XFS or
        # mounts with `nobarrier`, power loss can lose the new file's
        # contents while the old file's removal persists.
        try:
            fd = os.open(directory, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            # fsync of a directory can fail on some network filesystems;
            # the atomic rename itself has already succeeded.
            pass
    except Exception:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
