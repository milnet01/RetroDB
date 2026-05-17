# =============================================================================
# RETRODB - ROM Scanner (inline fallback)
# =============================================================================
# Used by /api/scan when scraper.scan_roms can't be imported. The primary
# scanner lives in scraper/scan_roms.py; this is a minimal ES-DE-style walker
# that covers the common case so the route still works in a stripped build.
# =============================================================================

import logging
import os
from datetime import datetime, timezone

import config
import settings_manager
from services.database import get_db_with_context
from services.game_utils import find_image_file

logger = logging.getLogger(__name__)


class RomPathNotConfigured(RuntimeError):
    """Raised when /api/scan (or either scanner) is invoked without a
    rom_path in settings.json.  The HTTP layer converts this to a 4xx with
    a remediation message instead of letting it surface as success-with-0,
    which the old code did by silently returning 0 from scan_roms().

    v3.6.5 — previously the scanner read config.ROM_PATH directly, which is
    the hardcoded `""` default (never mutated at runtime).  Effective path
    resolution lives in settings_manager.get_effective_path; the scanner
    must call it at runtime, not snapshot ROM_PATH at import time."""


_TAGS = (
    '(USA)', '(Europe)', '(Japan)', '(World)', '(En)', '(Fr)', '(De)', '(Es)', '(It)',
    '(U)', '(E)', '(J)', '(W)', '[!]', '(Rev', '(v', '[b', '[h', '[a', '[o', '[p', '[t', '[f',
    '(Demo)', '(Proto)', '(Beta)', '(Sample)', '(Unl)', '(Hack)', '(PD)', '(Pirate)',
)


def clean_title(filename):
    """Clean a ROM filename to a proper title."""
    name = os.path.splitext(filename)[0]
    for tag in _TAGS:
        if tag in name:
            name = name.split(tag)[0]
    name = name.replace('_', ' ').replace('  ', ' ').strip()
    return name


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


def run_inline_scan():
    """Inline ROM scanning when scraper.scan_roms module is not available."""
    new_games = 0

    rom_path = settings_manager.get_effective_path('rom_path', config.ROM_PATH)
    if not rom_path or not rom_path.strip():
        raise RomPathNotConfigured(
            "ROM path not configured. Go to Settings → Paths to set it."
        )

    with get_db_with_context() as conn:
        c = conn.cursor()

        for folder in sorted(os.listdir(rom_path)):
            system_path = os.path.join(rom_path, folder)

            if not os.path.isdir(system_path):
                continue

            system_name = config.SYSTEM_NAME_MAP.get(folder, folder.replace('_', ' ').title())

            logo_dir = os.path.join(config.STATIC_PATH, 'images', 'systems')
            logo_filename, _ = find_image_file(logo_dir, folder)
            system_logo = logo_filename

            c.execute("INSERT OR IGNORE INTO systems (name, folder, logo) VALUES (?, ?, ?)",
                      (system_name, folder, system_logo))
            c.execute("SELECT id FROM systems WHERE folder = ?", (folder,))
            row = c.fetchone()
            if not row:
                logger.warning(f"System not found for folder: {folder}")
                continue
            system_id = row[0]
            c.execute("UPDATE systems SET name = ?, logo = ? WHERE folder = ?",
                      (system_name, system_logo, folder))

            extensions = parse_systeminfo(system_path)

            if not extensions:
                continue

            for file in os.listdir(system_path):
                file_path = os.path.join(system_path, file)

                if not os.path.isfile(file_path):
                    continue

                ext = os.path.splitext(file)[1].lower()
                if ext not in extensions:
                    continue

                c.execute("SELECT id FROM games WHERE rom_path = ?", (file_path,))
                if c.fetchone():
                    continue

                title = clean_title(file)

                c.execute("""
                    INSERT INTO games (system_id, title, rom_path, scraped, created_at)
                    VALUES (?, ?, ?, 0, ?)
                """, (system_id, title, file_path, datetime.now(timezone.utc).isoformat()))

                new_games += 1

    logger.info(f"ROM scan complete. Found {new_games} new games.")
    return new_games
