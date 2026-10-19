# =============================================================================
# RETRODB - Per-game settings for standalone emulators (PASS-59-91 §4.6)
# =============================================================================
# DuckStation, PCSX2 and RPCS3 read per-game settings from a file named by the
# disc serial. At launch RetroDB writes its managed keys (resolution scale,
# aspect ratio, and RPCS3's fullscreen) into that file, line by line, leaving
# every other line alone. A key the user set inside the emulator is theirs:
# RetroDB rewrites a key only where the file still holds what RetroDB last
# wrote (`emulator_written_settings`). Choices: the game's, else the system's,
# else the table's default (data/standalone_settings.json).
#
# Nothing here raises into a launch: a missing data dir, an unreadable serial
# or two PCSX2 candidates leave the file alone and the launch goes ahead (§6).
# =============================================================================

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from functools import lru_cache
from pathlib import Path
from typing import Optional

from services.database import query, get_db_with_context
from services.disc_serial import CRC_RE, SERIAL_RE, read_disc_ids

logger = logging.getLogger(__name__)

TABLE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'standalone_settings.json'


@lru_cache(maxsize=1)
def _table() -> dict:
    with open(TABLE_PATH, encoding='utf-8') as f:
        return {k: v for k, v in json.load(f).items() if not k.startswith('_')}


def settings_for(binary_name: str) -> dict:
    """{setting: spec} RetroDB manages for this emulator; {} if none."""
    return _table().get(binary_name or '', {})


def choice_keys(spec: dict) -> list:
    return list(spec['flag'] if 'flag' in spec else spec['values'])


def flag_args(spec: Optional[dict], choice: Optional[str]) -> list:
    """{fullscreen_flag}'s argv words: the adapter's flag for the effective
    choice, or none for an emulator with no flag (§4.6, INV-17)."""
    if not spec or 'flag' not in spec:
        return []
    value = choice if choice in spec['flag'] else spec['default']
    return [spec['flag'][value]]


# -----------------------------------------------------------------------------
# Choices
# -----------------------------------------------------------------------------

def _choices(emulator_id, system_id, game_id) -> dict:
    """{setting: (value, source)} for the game and system scopes."""
    rows = query("""
        SELECT scope, setting, value FROM emulator_setting_choices
        WHERE emulator_id = ? AND ((scope = 'system' AND scope_id = ?)
                                   OR (scope = 'game' AND scope_id = ?))
    """, (emulator_id, system_id, game_id or -1))
    out = {}
    for scope in ('system', 'game'):          # game wins (INV-13)
        for r in rows:
            if r['scope'] == scope:
                out[r['setting']] = (r['value'], scope)
    return out


def effective(spec, chosen) -> tuple:
    """(choice, source) — the chosen value if still offered, else the default."""
    if chosen and chosen[0] in choice_keys(spec):
        return chosen
    return spec['default'], 'default'


def set_choice(emulator_id, scope, scope_id, setting, value) -> None:
    """Record a choice; `value` None removes it. Raises ValueError for a
    setting or value the table does not offer."""
    emu = query("SELECT binary_name FROM emulators WHERE id = ?", (emulator_id,), one=True)
    spec = settings_for(emu['binary_name'] if emu else '').get(setting)
    if not spec:
        raise ValueError(f'unknown setting {setting!r}')
    if value is not None and value not in choice_keys(spec):
        raise ValueError(f'unknown value {value!r} for {setting}')
    with get_db_with_context() as conn:
        if value is None:
            conn.execute("""DELETE FROM emulator_setting_choices WHERE emulator_id = ?
                            AND scope = ? AND scope_id = ? AND setting = ?""",
                         (emulator_id, scope, scope_id, setting))
        else:
            conn.execute("""
                INSERT INTO emulator_setting_choices (emulator_id, scope, scope_id, setting, value)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT (emulator_id, scope, scope_id, setting) DO UPDATE SET value = excluded.value
            """, (emulator_id, scope, scope_id, setting, value))
        conn.commit()


# -----------------------------------------------------------------------------
# File editing — line by line, never through configparser or PyYAML
# -----------------------------------------------------------------------------

def _ini_find(lines, section, key):
    """(index of the [section] line or None, index of the key line or None,
    index to insert a new key at)."""
    sec_idx, key_idx, insert = None, None, None
    key_re = re.compile(rf'^\s*{re.escape(key)}\s*=')
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            if sec_idx is not None:
                break
            if stripped[1:-1] == section:
                sec_idx, insert = i, i + 1
            continue
        if sec_idx is not None:
            if stripped:
                insert = i + 1
            if key_re.match(line):
                key_idx = i
    return sec_idx, key_idx, insert


def _yaml_find(lines, block, key):
    blk_idx, key_idx, insert = None, None, None
    key_re = re.compile(rf'^  {re.escape(key)}:(\s|$)')
    for i, line in enumerate(lines):
        if blk_idx is None:
            if line.rstrip() == f'{block}:':
                blk_idx, insert = i, i + 1
            continue
        if line.strip() and not line.startswith(' '):
            break
        if line.strip():
            insert = i + 1
        if key_re.match(line):
            key_idx = i
    return blk_idx, key_idx, insert


def _where(spec):
    return ('yaml', spec['path'][0], spec['path'][1]) if 'path' in spec \
        else ('ini', spec['section'], spec['key'])


def read_value(lines, spec) -> Optional[str]:
    """The text after `=` or `:` for this setting, trimmed; None if absent."""
    kind, block, key = _where(spec)
    _, idx, _ = (_yaml_find if kind == 'yaml' else _ini_find)(lines, block, key)
    if idx is None:
        return None
    return lines[idx].split(':' if kind == 'yaml' else '=', 1)[1].strip()


def write_value(lines, spec, raw) -> list:
    kind, block, key = _where(spec)
    find = _yaml_find if kind == 'yaml' else _ini_find
    new = f'  {key}: {raw}\n' if kind == 'yaml' else f'{key} = {raw}\n'
    head, idx, insert = find(lines, block, key)
    lines = list(lines)
    if idx is not None:
        lines[idx] = new
    elif head is not None:
        lines.insert(insert, new)
    else:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        if lines and lines[-1].strip() and kind == 'ini':
            lines.append('\n')
        lines += [f'{block}:\n' if kind == 'yaml' else f'[{block}]\n', new]
    return lines


# -----------------------------------------------------------------------------
# Which file (§4.6 "Which file")
# -----------------------------------------------------------------------------

def _disc_ids(game) -> tuple:
    """(serial, crc), read from the disc and stored the first time."""
    if game.get('disc_serial') is not None:
        return game['disc_serial'], game.get('disc_crc')
    serial, crc = read_disc_ids(game['rom_path'], game['system_folder'])
    with get_db_with_context() as conn:
        conn.execute("UPDATE games SET disc_serial = ?, disc_crc = ? WHERE id = ?",
                     (serial, crc, game['id']))
        conn.commit()
    return serial, crc


def _target(binary_name, data_dir: Path, serial, crc) -> dict:
    """{'file': Path or None, 'reason': str or None, 'candidates': [str]}."""
    if not SERIAL_RE.match(serial or ''):
        return {'file': None, 'candidates': [],
                'reason': "RetroDB could not read this disc's serial, so it cannot "
                          "name the emulator's per-game settings file."}
    candidates = []
    if binary_name == 'duckstation-qt':
        path = data_dir / 'gamesettings' / f'{serial}.ini'
    elif binary_name == 'pcsx2-qt':
        found = sorted((data_dir / 'gamesettings').glob(f'{serial}_*.ini'))
        candidates = [str(p) for p in found]
        if len(found) > 1:
            return {'file': None, 'candidates': candidates,
                    'reason': 'PCSX2 has two or more settings files for this game; '
                              'remove the ones you do not use.'}
        if found:
            path = found[0]
        elif CRC_RE.match(crc or ''):
            path = data_dir / 'gamesettings' / f'{serial}_{crc}.ini'
        else:
            return {'file': None, 'candidates': [],
                    'reason': "RetroDB could not read this disc's boot file, so it "
                              "cannot name PCSX2's per-game settings file."}
        candidates = []
    else:
        path = data_dir / 'custom_configs' / f"config_{serial.replace('-', '')}.yml"
    try:
        path.resolve().relative_to(data_dir.resolve())
    except ValueError:
        return {'file': None, 'candidates': [], 'reason': 'Settings path outside the data folder.'}
    return {'file': path, 'reason': None, 'candidates': candidates}


def _context(game_id) -> dict:
    """Everything a view or a launch needs: the game, the emulator the
    resolver would pick, its settings table, data dir and file."""
    from services.emulator_adapters import adapter_for, find_data_dir
    from services.launch_resolver import LaunchResolutionError, _pick_mapping, _resolve_binary
    game = query("""
        SELECT g.id, g.system_id, g.rom_path, g.emulator_override_id, g.disc_serial,
               g.disc_crc, s.folder AS system_folder, s.name AS system_name
        FROM games g JOIN systems s ON s.id = g.system_id WHERE g.id = ?
    """, (game_id,), one=True)
    if not game:
        return {'game': None}
    ctx = {'game': game, 'emulator': None, 'table': {}, 'file': None,
           'reason': None, 'candidates': [], 'serial': game.get('disc_serial')}
    try:
        emu, sys_emu = _pick_mapping(game['system_id'], game.get('emulator_override_id'),
                                     game['system_name'])
    except LaunchResolutionError:
        ctx['reason'] = 'No emulator is set up for this system.'
        return ctx
    ctx['emulator'] = emu
    ctx['table'] = settings_for(emu['binary_name'] if emu else '')
    if not ctx['table']:
        ctx['reason'] = ('RetroDB manages per-game settings for DuckStation, '
                         'PCSX2 and RPCS3 only.')
        return ctx
    adapter = adapter_for(emu)
    try:
        binary = Path(_resolve_binary(emu, sys_emu))
    except LaunchResolutionError:
        binary = None
    data_dir = find_data_dir(adapter, binary) if adapter and binary else None
    if data_dir is None:
        ctx['reason'] = (f"Run {emu['name']} once so it creates its settings, "
                         'then play again.')
        return ctx
    serial, crc = _disc_ids(game)
    ctx['serial'] = serial
    ctx.update(_target(emu['binary_name'], data_dir, serial, crc))
    return ctx


def _read_lines(path: Path) -> list:
    if not path.exists():
        return []
    with open(path, encoding='utf-8') as f:
        return f.readlines()


def _written(path: Path) -> dict:
    rows = query("SELECT setting, written FROM emulator_written_settings WHERE file_path = ?",
                 (str(path),))
    return {r['setting']: r['written'] for r in rows}


# -----------------------------------------------------------------------------
# Public
# -----------------------------------------------------------------------------

def apply_for_launch(game_id) -> Optional[str]:
    """Write RetroDB's managed keys into the game's per-game file, before the
    emulator starts. Returns the file written, or None. Never raises."""
    try:
        ctx = _context(game_id)
        path = ctx.get('file')
        if not path:
            return None
        emu = ctx['emulator']
        lines = _read_lines(path)
        before = list(lines)
        written = _written(path)
        chosen = _choices(emu['id'], ctx['game']['system_id'], game_id)
        records = []
        for setting, spec in ctx['table'].items():
            if 'flag' in spec:
                continue
            current = read_value(lines, spec)
            if current is not None and written.get(setting) != current:
                continue                     # the user's own (step 1)
            value, _src = effective(spec, chosen.get(setting))
            raw = spec['values'][value]
            if current != raw:
                lines = write_value(lines, spec, raw)
            records.append((setting, raw))
        if lines != before:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=path.parent, prefix='.retrodb-')
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.writelines(lines)
            os.replace(tmp, path)
        with get_db_with_context() as conn:
            conn.executemany("""
                INSERT INTO emulator_written_settings (emulator_id, file_path, setting, written)
                VALUES (?, ?, ?, ?)
                ON CONFLICT (file_path, setting) DO UPDATE SET written = excluded.written,
                                                               emulator_id = excluded.emulator_id
            """, [(emu['id'], str(path), s, raw) for s, raw in records])
            conn.commit()
        return str(path)
    except Exception as e:  # noqa: BLE001 — a settings problem never stops a launch (§6)
        logger.warning(f"standalone settings: not written for game {game_id}: {e}")
        return None


def _labels(spec) -> dict:
    return {k: k for k in choice_keys(spec)}


def game_view(game_id) -> Optional[dict]:
    """GET /api/games/<id>/emulator-settings; None when the game is missing."""
    ctx = _context(game_id)
    if not ctx.get('game'):
        return None
    emu = ctx['emulator']
    settings = []
    if emu and ctx['table']:
        chosen = _choices(emu['id'], ctx['game']['system_id'], game_id)
        path = ctx.get('file')
        lines = _read_lines(path) if path else []
        written = _written(path) if path else {}
        for setting, spec in ctx['table'].items():
            value, source = effective(spec, chosen.get(setting))
            current = read_value(lines, spec) if 'flag' not in spec else None
            if current is not None and written.get(setting) != current:
                raw_to_key = {raw: k for k, raw in spec['values'].items()}
                value, source = raw_to_key.get(current, current), 'emulator'
            settings.append({'setting': setting, 'value': value, 'source': source,
                             'values': choice_keys(spec), 'per_game': 'flag' not in spec})
    return {
        'supported': bool(ctx.get('file')),
        'reason': None if ctx.get('file') else ctx.get('reason'),
        'candidates': ctx.get('candidates', []),
        'emulator': {'id': emu['id'], 'name': emu['name']} if emu else None,
        'serial': ctx.get('serial') or None,
        'file': str(ctx['file']) if ctx.get('file') else None,
        'settings': settings,
    }


def system_view(system_id, emulator_id) -> Optional[dict]:
    """GET /api/systems/<sid>/emulator-settings/<eid>."""
    emu = query("SELECT id, name, binary_name FROM emulators WHERE id = ?",
                (emulator_id,), one=True)
    if not emu:
        return None
    table = settings_for(emu['binary_name'])
    chosen = _choices(emulator_id, system_id, None)
    return {
        'supported': bool(table),
        'emulator': {'id': emu['id'], 'name': emu['name']},
        'settings': [dict(zip(('value', 'source'), effective(spec, chosen.get(setting))),
                          setting=setting, values=choice_keys(spec))
                     for setting, spec in table.items()],
    }
