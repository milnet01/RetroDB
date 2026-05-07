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
import tempfile


__all__ = [
    'atomic_write_json',
    'atomic_write_bytes',
    'atomic_write_text',
    'fsync_path',
]


def fsync_path(path):
    """Open `path` read-only and fsync its file descriptor.

    Works for both regular files and directories — on POSIX, fsyncing a
    directory flushes the directory's own metadata (i.e. the rename/create
    entries under it) so a crash after os.replace can't lose the new name.
    """
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path, data, *, mode=0o644, fsync_dir=True):
    """Atomically write `data` (bytes) to `path` (Pass 45.5).

    Sequence: ``mkstemp`` in the same directory → write → ``flush`` →
    ``fsync(fd)`` → ``chmod`` the tmpfile → ``os.replace`` → fsync the
    parent directory. The chmod fires on the tmpfile *before* the rename,
    so the final path never exists at the umask default — important when
    ``mode=0o600`` (secret key, DB backup) and the umask is the typical
    0o022.

    Replaces four ad-hoc copies of this dance that had drifted: some
    skipped fsync (power-loss exposure), some chmod'd after re-opening for
    a verify pass (0o644 window while the file held secrets), some used a
    static ``.tmp`` suffix (race-prone with concurrent processes).

    Args:
        path: Destination path.
        data: Bytes to write.
        mode: File mode after the rename (default 0o644).
        fsync_dir: If True, fsync the parent directory after the rename so
            the directory entry survives a power loss.
    """
    if isinstance(data, str):
        raise TypeError(
            "atomic_write_bytes requires bytes; use atomic_write_text"
        )
    directory = os.path.dirname(path) or '.'
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix='.atomic_', dir=directory)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        try:
            os.chmod(tmp_path, mode)
        except OSError:
            pass
        os.replace(tmp_path, path)
        tmp_path = None
        if fsync_dir:
            try:
                fsync_path(directory)
            except OSError:
                pass
    finally:
        if tmp_path is not None and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def atomic_write_text(path, text, *, encoding='utf-8', mode=0o644, fsync_dir=True):
    """UTF-8 wrapper over :func:`atomic_write_bytes`."""
    if not isinstance(text, str):
        raise TypeError(
            "atomic_write_text requires str; use atomic_write_bytes"
        )
    atomic_write_bytes(
        path, text.encode(encoding), mode=mode, fsync_dir=fsync_dir,
    )


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
