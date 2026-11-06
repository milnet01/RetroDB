# =============================================================================
# RETRODB - ROM scanning helpers
# =============================================================================
# The scanner itself is scraper/scan_roms.py. This holds what other code
# shares with it: the unset-path error and the ROM-type check. The inline
# fallback scanner that lived here was removed (PASS-59-249): it skipped the
# main scanner's hidden-file, PS3 and special-folder handling.
# =============================================================================

import logging
import os


logger = logging.getLogger(__name__)


class RomPathNotConfigured(RuntimeError):
    """Raised when /api/scan (the scanner) is invoked without a
    rom_path in settings.json.  The HTTP layer converts this to a 4xx with
    a remediation message instead of letting it surface as success-with-0,
    which the old code did by silently returning 0 from scan_roms().

    v3.6.5 — previously the scanner read config.ROM_PATH directly, which is
    the hardcoded `""` default (never mutated at runtime).  Effective path
    resolution lives in settings_manager.get_effective_path; the scanner
    must call it at runtime, not snapshot ROM_PATH at import time."""


def parse_systeminfo(system_path):
    """Parse ES-DE systeminfo.txt for supported file extensions."""
    info_file = os.path.join(system_path, 'systeminfo.txt')
    extensions = set()

    if not os.path.exists(info_file):
        return extensions

    current_key = None

    with open(info_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()

            if not line:
                current_key = None
                continue

            if line.endswith(':'):
                current_key = line[:-1].strip().lower()
                continue

            if current_key == 'supported file extensions':
                for ext in line.split():
                    if ext.startswith('.'):
                        extensions.add(ext.lower())

    return extensions


def rom_type_problem(rom_path, rom_root):
    """Why `rom_path` is not a ROM type its system lists, or None if it is.

    The system folder is the first folder under `rom_root`, as the scanners
    walk it; its systeminfo.txt holds the allowed extensions. A missing or
    empty list is a problem too, since the scan admits nothing there
    (PASS-59-95). `rom_path` may be a name not yet on disk, for a rename.
    """
    try:
        rel = os.path.relpath(os.path.realpath(os.path.dirname(rom_path)),
                              os.path.realpath(rom_root))
    except ValueError:
        rel = os.pardir
    folder = rel.split(os.sep)[0]
    if folder in ('', os.curdir, os.pardir):
        return f"{rom_path} is not inside a system folder under {rom_root}"
    system_path = os.path.join(rom_root, folder)
    extensions = parse_systeminfo(system_path)
    if not extensions:
        return ("no file types are listed for this system: "
                f"{os.path.join(system_path, 'systeminfo.txt')} is missing or empty")
    ext = os.path.splitext(rom_path)[1].lower()
    if ext not in extensions:
        return (f"'{ext or '(none)'}' is not a ROM type for this system "
                f"(allowed: {' '.join(sorted(extensions))})")
    return None
