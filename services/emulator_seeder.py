# =============================================================================
# RETRODB - Emulator seed loader
# =============================================================================
# Seeds the `emulators` and `system_emulators` tables from a JSON file.
# Idempotent: keyed on emulators.name (UNIQUE) and (system_id, emulator_id)
# (UNIQUE). Re-running produces no diff. Mappings that reference an absent
# system folder are skipped silently — installs that don't have every system
# scanned-in still get a clean seed.
#
# Invoked from app.py on startup, AFTER migration 010 has been applied.
# =============================================================================

import json
import logging

logger = logging.getLogger(__name__)


def seed_emulators_from_file(conn, path):
    """Read JSON at `path` and seed emulators + system_emulators idempotently."""
    with open(path, 'r', encoding='utf-8') as f:
        seed = json.load(f)

    c = conn.cursor()

    for emu in seed.get('emulators', []):
        c.execute("""
            INSERT OR IGNORE INTO emulators
            (name, binary_name, args_template, is_retroarch, description, enabled, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, datetime('now'), datetime('now'))
        """, (
            emu['name'],
            emu['binary_name'],
            emu['args_template'],
            int(emu.get('is_retroarch', 0)),
            emu.get('description'),
        ))

    for sm in seed.get('system_emulators', []):
        sys_row = c.execute("SELECT id FROM systems WHERE folder = ?", (sm['system_folder'],)).fetchone()
        if not sys_row:
            logger.debug("seed: system folder %r not present; skipping", sm['system_folder'])
            continue
        emu_row = c.execute("SELECT id FROM emulators WHERE name = ?", (sm['emulator_name'],)).fetchone()
        if not emu_row:
            logger.warning("seed: emulator %r referenced by mapping but missing", sm['emulator_name'])
            continue
        c.execute("""
            INSERT OR IGNORE INTO system_emulators
            (system_id, emulator_id, is_default, retroarch_core, extra_args)
            VALUES (?, ?, ?, ?, ?)
        """, (
            sys_row[0],
            emu_row[0],
            int(sm.get('is_default', 0)),
            sm.get('retroarch_core'),
            sm.get('extra_args'),
        ))

    conn.commit()
    logger.info("emulator seed applied from %s", path)
