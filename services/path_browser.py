# =============================================================================
# RETRODB - What the Browse button on a path field lists
# =============================================================================
# The folders, and for a program's path the files, in one folder on the
# computer RetroDB runs on. The setup wizard and the admin route use it.
# =============================================================================

import os
import string

import platform_utils


def start_folder(typed) -> str:
    """The folder to open for what a field holds: the path itself, or the
    nearest folder above it that exists. Anything that is not a full path,
    such as `flatpak run ...`, opens the home folder."""
    home = os.path.expanduser('~')
    path = os.path.expanduser(typed) if typed else ''
    if not os.path.isabs(path):
        return home
    path = os.path.abspath(path)
    while not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            return home
        path = parent
    return path


def _sorted(entries):
    """By name, ignoring case, with hidden entries after the rest."""
    return sorted(entries, key=lambda e: (e.name.startswith('.'), e.name.casefold()))


def _counts(path):
    """(files, subfolders) directly inside `path`; (0, 0) if unreadable."""
    files = folders = 0
    try:
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_file():
                    files += 1
                elif entry.is_dir():
                    folders += 1
    except OSError:
        return 0, 0
    return files, folders


def _drives():
    """Windows' drive letters; A and B are left out, because asking about an
    empty floppy drive can stall."""
    if not platform_utils.IS_WINDOWS:
        return []
    letters = (f'{c}:\\' for c in string.ascii_uppercase[2:])
    return [d for d in letters if os.path.isdir(d)]


def list_path(path, include_files=False, include_hidden=True) -> dict:
    """One folder's contents. Raises PermissionError if it cannot be read."""
    folders, files = [], []
    with os.scandir(path) as entries:
        for entry in _sorted(entries):
            if entry.name.startswith('.') and not include_hidden:
                continue
            try:
                is_dir, is_file = entry.is_dir(), entry.is_file()
            except OSError:
                continue
            if is_dir:
                file_count, subfolder_count = _counts(entry.path)
                folders.append({'name': entry.name, 'path': entry.path,
                                'file_count': file_count,
                                'subfolder_count': subfolder_count})
            elif is_file and include_files:
                files.append({'name': entry.name, 'path': entry.path})
    parent = os.path.dirname(path)
    return {
        'base_path': os.path.expanduser('~'),
        'current_path': path,
        'parent_path': parent if parent != path else None,
        'folders': folders,
        'files': files,
        'drives': _drives(),
        'is_root': parent == path,
    }
