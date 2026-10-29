# =============================================================================
# RETRODB - Cheats for the player, DuckStation and PCSX2 (PASS-59-155)
# =============================================================================
# The game page lists the cheats RetroDB found for a game, one switch each,
# and the game starts with the switched-on ones. The store has two layers:
#
#   data/cheats/packs/<pack>/   what a download wrote; replaced whole
#   data/cheats/own/<kind>/     what an import copied; a download never
#                               touches it, and it wins over a pack file
#                               of the same name
#
# Each emulator's own files are the record of what is on: the player's in
# the game's .cht, DuckStation's and PCSX2's in their per-game settings
# file. RetroDB keeps no table of switches (§4.5).
#
#   download_pack() / import_folder()     fill the store (§4.2, §4.3)
#   game_view() / save()                  the Cheats panel (§4.6, §4.7)
#   place_for_launch() / take_back()      the player's copy, around a session
# =============================================================================

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path, PurePosixPath
from typing import Optional
from urllib.parse import urlparse

import requests
from flask_babel import lazy_gettext as _

import config
from services.disc_serial import SERIAL_RE

logger = logging.getLogger(__name__)

PACKS = {
    'retroarch': 'https://buildbot.libretro.com/assets/frontend/cheats.zip',
    'duckstation': 'https://github.com/duckstation/chtdb/releases/download/latest/cheats.zip',
    'pcsx2': 'https://github.com/xs1l3n7x/pcsx2_cheats_collection/archive/refs/heads/main.zip',
}
_EXT = {'retroarch': '.cht', 'duckstation': '.cht', 'pcsx2': '.pnach'}
MAX_PACK_BYTES = 1024 * 1024 * 1024    # unpacked, as the shader pack (§13)
MAX_FILE_BYTES = 8 * 1024 * 1024       # one cheat file an import or the panel reads
_CHUNK = 1024 * 1024

# DuckStation's emulator id, main settings file, and the section holding
# EnableCheats; PCSX2's the same (§4.5).
_STANDALONE = {'duckstation-qt': ('duckstation', 'settings.ini', 'Cheats'),
               'pcsx2-qt': ('pcsx2', 'inis/PCSX2.ini', 'EmuCore')}

# Wider than disc_serial.SERIAL_RE: the DuckStation pack also names discs
# such as SLP-86051, and an import keeps those files.
_DS_NAME = re.compile(r'^[A-Z]{3,4}-\d{4,5}')
_PNACH_NAME = re.compile(r'^(?:[A-Z]{4}-\d{5}_)?[0-9A-F]{8}(?![0-9A-Za-z])')
_GAMETITLE = re.compile(r'^\s*gametitle\s*=.*\[([^\]]*)\]\s*\[([0-9A-Fa-f]{8})\]\s*$',
                        re.M | re.I)
_RA_COUNT = re.compile(r'^\s*cheats\s*=\s*"?(\d+)', re.M)
_CHT_KEY = re.compile(r'^\s*cheat(\d+)_(desc|enable)\s*=\s*"?(.*?)"?\s*$')
_SECTION = re.compile(r'^\s*\[(.+)\]\s*$')
_PATCH = re.compile(r'^\s*patch\s*=', re.I)
_GROUPS = re.compile(r'\(([^)]*)\)|\[([^\]]*)\]')


# Where a pack download may end up. GitHub answers both of its URLs with a
# redirect to another of its hosts, so redirects are followed; with no
# checksum published, the final host is what is checked.
_PACK_HOSTS = {'buildbot.libretro.com', 'github.com', 'codeload.github.com',
               'objects.githubusercontent.com', 'release-assets.githubusercontent.com'}


class CheatError(Exception):
    """A download, import or save that did nothing; the message says why."""


def _http_get(url: str, stream: bool = False):
    r = requests.get(url, stream=stream, timeout=30)
    host = urlparse(r.url).hostname
    if host not in _PACK_HOSTS:
        r.close()
        raise CheatError(f'the download moved to an unexpected host: {host}')
    return r


# -----------------------------------------------------------------------------
# The store
# -----------------------------------------------------------------------------

def store_dir() -> Path:
    """Read per call so a test can move BASE_DIR."""
    return Path(config.BASE_DIR).resolve() / 'data' / 'cheats'


def cheats_folder(folder) -> Optional[str]:
    """The libretro cheat-pack folder of a system. Read from the system's
    own entry, never through `same_as`: Game Boy Color shares Game Boy's
    cores, not its cheats."""
    from services import player_cores
    if not folder or folder.startswith('_'):
        return None
    return (player_cores._raw().get(folder) or {}).get('cheats')


def _store_files(kind, sub='') -> dict:
    """{file name: Path} in one store folder, own/ winning over packs/."""
    found = {}
    for layer in ('packs', 'own'):
        d = store_dir() / layer / kind / sub
        if d.is_dir():
            for p in d.iterdir():
                if p.is_file() and p.suffix.lower() == _EXT[kind]:
                    found[p.name] = p
    return found


def _rel(path: Path) -> str:
    return path.relative_to(store_dir()).as_posix()


def _copy(src: Path, dest: Path) -> None:
    """Copy in one step, so nobody reads a half-written file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix='.retrodb-')
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dest)
    finally:
        Path(tmp).unlink(missing_ok=True)


def _read_text(path: Path) -> str:
    if path.stat().st_size > MAX_FILE_BYTES:
        raise CheatError(_('%(name)s is too large to be a cheat file.', name=path.name))
    return path.read_text(encoding='utf-8', errors='replace')


# -----------------------------------------------------------------------------
# Packs (§4.2)
# -----------------------------------------------------------------------------

def pack_sources() -> dict:
    """{pack: {url, downloaded_at, files}} for the packs downloaded."""
    try:
        return json.loads((store_dir() / 'sources.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _pack_member(pack, info) -> Optional[Path]:
    """Where a zip member goes inside the pack's folder; None to skip it."""
    if info.is_dir():
        return None
    parts = PurePosixPath(info.filename).parts
    if not parts or not parts[-1].lower().endswith(_EXT[pack]):
        return None
    if pack == 'retroarch':                 # <system folder>/<title>.cht
        return Path(*parts) if len(parts) == 2 else None
    if pack == 'duckstation':               # <SERIAL>.cht at the top
        return Path(parts[-1]) if len(parts) == 1 else None
    return Path(parts[-1]) if len(parts) >= 2 and parts[-2] == 'cheats' else None


def download_pack(pack) -> int:
    """Download a pack into packs/<pack>/, whole or not at all, and return
    its file count. No checksum is published for any pack."""
    from services import player_cores
    if pack not in PACKS:
        raise CheatError(f'{pack!r} is not a cheat pack')
    packs = store_dir() / 'packs'
    part = packs / f'.{pack}.zip.part'
    staging = None
    try:
        packs.mkdir(parents=True, exist_ok=True)
        player_cores._download(PACKS[pack], part, get=_http_get)
        staging = Path(tempfile.mkdtemp(dir=packs, prefix=f'.{pack}-'))
        root = staging.resolve()
        count = total = 0
        with zipfile.ZipFile(part) as zf:
            for info in zf.infolist():
                target = (staging / info.filename).resolve()
                if target != root and root not in target.parents:   # INV-7
                    raise CheatError(f'unsafe path in the {pack} pack: {info.filename}')
                rel = _pack_member(pack, info)
                if rel is None:
                    continue
                total += info.file_size
                if total > MAX_PACK_BYTES:
                    raise CheatError(f'the {pack} pack is larger than 1 GiB')
                dest = staging / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(info) as src, open(dest, 'wb') as out:
                    shutil.copyfileobj(src, out, _CHUNK)
                count += 1
        dest = packs / pack
        old = None
        if dest.exists():
            old = packs / f'.{pack}-old-{os.getpid()}'
            shutil.rmtree(old, ignore_errors=True)
            os.replace(dest, old)
        os.replace(staging, dest)
        staging = None
        if old:
            shutil.rmtree(old, ignore_errors=True)
        sources = pack_sources()
        sources[pack] = {'url': PACKS[pack], 'files': count,
                         'downloaded_at': time.strftime('%Y-%m-%d %H:%M')}
        (store_dir() / 'sources.json').write_text(json.dumps(sources, indent=1, sort_keys=True),
                                                  encoding='utf-8')
        return count
    except player_cores.CoreInstallError as e:
        raise CheatError(str(e)) from e
    except zipfile.BadZipFile as e:
        raise CheatError(f'the {pack} pack is not a zip') from e
    except (OSError, requests.RequestException) as e:
        raise CheatError(str(e)) from e
    finally:
        part.unlink(missing_ok=True)
        if staging:
            shutil.rmtree(staging, ignore_errors=True)


# -----------------------------------------------------------------------------
# Import (§4.3)
# -----------------------------------------------------------------------------

def _known_folders() -> set:
    """libretro system folders: the table's and the downloaded pack's."""
    from services import player_cores
    found = {e['cheats'] for k, e in player_cores._raw().items()
             if not k.startswith('_') and 'cheats' in e}
    pack = store_dir() / 'packs' / 'retroarch'
    if pack.is_dir():
        found |= {p.name for p in pack.iterdir() if p.is_dir()}
    return found


def _system_folder(parent, stem, folders) -> Optional[str]:
    """The system folder for a RetroArch file in folder `parent`: the name
    itself, or the one system a core library name serves. A core serving
    several (Gambatte: Game Boy and Color) picks the one whose pack holds a
    file of the same name; otherwise None."""
    if parent in folders:
        return parent
    from services import player_cores
    raw = player_cores._raw()
    cores = {c for c, n in raw.get('_library_names', {}).items() if n == parent}
    options = sorted({cheats_folder(k) for k in raw
                      if cheats_folder(k) and set(player_cores.cores_for(k)) & cores})
    if len(options) == 1:
        return options[0]
    pack = store_dir() / 'packs' / 'retroarch'
    hits = [o for o in options if (pack / o / f'{stem}.cht').is_file()]
    return hits[0] if len(hits) == 1 else None


def _sort(f: Path, folders) -> tuple:
    """(destination under own/, None) or (None, reason), by what the file
    holds rather than where it sits."""
    own = store_dir() / 'own'
    ext = f.suffix.lower()
    if ext not in ('.cht', '.pnach'):
        return None, _('Not a cheat file.')
    text = _read_text(f)
    if ext == '.pnach':
        if _PNACH_NAME.match(f.stem):
            return own / 'pcsx2' / f.name, None
        m = _GAMETITLE.search(text)
        if not m:
            return None, _('A PCSX2 file with no CRC in its name or its gametitle line.')
        serial, crc = m.group(1).strip(), m.group(2).upper()
        name = f'{serial}_{crc}' if SERIAL_RE.match(serial) else crc
        return own / 'pcsx2' / f'{name}.pnach', None
    if _RA_COUNT.search(text):
        folder = _system_folder(f.parent.name, f.stem, folders)
        if not folder:
            return None, _('A RetroArch file whose folder names no single system.')
        return own / 'retroarch' / folder / f.name, None
    if _sections(text):
        if _DS_NAME.match(f.name):
            return own / 'duckstation' / f.name, None
        return None, _('A DuckStation file not named by its serial.')
    return None, _('Not a cheat file.')


def import_folder(path) -> dict:
    """Copy every cheat file under `path` into own/, sorted by content. The
    source is only read. Returns {copied: {kind: n}, unchanged, skipped}."""
    src = Path(str(path or '').strip()).expanduser()
    if not str(path or '').strip() or not src.is_dir():
        raise CheatError(_('That folder was not found.'))
    root = store_dir().resolve()
    if src.resolve() == root or root in src.resolve().parents:
        raise CheatError(_("That folder is RetroDB's own cheat store."))
    result = {'copied': {k: 0 for k in PACKS}, 'unchanged': 0, 'skipped': []}
    folders = _known_folders()
    for f in sorted(src.rglob('*')):
        if not f.is_file() or root in f.resolve().parents:
            continue
        try:
            dest, reason = _sort(f, folders)
            if dest is not None and dest.is_file() and dest.read_bytes() == f.read_bytes():
                result['unchanged'] += 1
                continue
            if dest is not None:
                _copy(f, dest)
        except (OSError, CheatError) as e:
            dest, reason = None, e
        if dest is None:
            result['skipped'].append({'file': str(f), 'reason': str(reason)})
        else:
            result['copied'][dest.relative_to(root / 'own').parts[0]] += 1
    return result


# -----------------------------------------------------------------------------
# File formats
# -----------------------------------------------------------------------------

def parse_cht(text) -> list:
    """[{name, enabled}] from a RetroArch .cht, in cheat order. A cheat with
    no description is named by its number."""
    count = _RA_COUNT.search(text)
    desc, enable = {}, {}
    for line in text.splitlines():
        m = _CHT_KEY.match(line)
        if m:
            (desc if m.group(2) == 'desc' else enable)[int(m.group(1))] = m.group(3)
    return [{'name': desc.get(i) or f'Cheat {i + 1}',
             'enabled': enable.get(i, '').lower() == 'true'}
            for i in range(int(count.group(1)) if count else 0)]


def _set_cht(text, enabled) -> str:
    """The .cht with each cheat's `cheatN_enable` set from `enabled` names;
    every other line kept."""
    want = {i: 'true' if c['name'] in enabled else 'false'
            for i, c in enumerate(parse_cht(text))}
    out, seen = [], set()
    for line in text.splitlines(True):
        m = _CHT_KEY.match(line)
        if m and m.group(2) == 'enable' and int(m.group(1)) in want:
            i = int(m.group(1))
            out.append(f'cheat{i}_enable = "{want[i]}"\n')
            seen.add(i)
        else:
            out.append(line)
    if out and not out[-1].endswith('\n'):
        out[-1] += '\n'
    out += [f'cheat{i}_enable = "{v}"\n' for i, v in want.items() if i not in seen]
    return ''.join(out)


def _sections(text) -> list:
    """The `[name]` cheats of a DuckStation .cht or PCSX2 .pnach, in order."""
    names = []
    for line in text.splitlines():
        m = _SECTION.match(line)
        if m and m.group(1).strip() not in names:
            names.append(m.group(1).strip())
    return names


def _ungrouped_patches(text) -> bool:
    """A .pnach patch line before its first group, which PCSX2 always
    applies while cheats are on."""
    for line in text.splitlines():
        if _SECTION.match(line):
            return False
        if _PATCH.match(line):
            return True
    return False


# -----------------------------------------------------------------------------
# Which list belongs to a game (§4.4)
# -----------------------------------------------------------------------------

def normalise(name) -> str:
    """Drop every (...) and [...] group, lowercase, one space per run of
    anything that is not a letter or digit."""
    return re.sub(r'[\W_]+', ' ', _GROUPS.sub(' ', name).lower()).strip()


def _tags(name) -> set:
    return {(a or b).strip().lower() for a, b in _GROUPS.findall(name)}


def player_candidates(system_folder, rom_path, title) -> list:
    """Store files (relative to the store) that may be this game's list,
    best first: the ROM file's name, else the title; then an exact name,
    then most shared bracket tags, then by name."""
    folder = cheats_folder(system_folder)
    if not folder:
        return []
    files = _store_files('retroarch', folder)
    stem = Path(rom_path).stem
    hits = []
    for want in (normalise(stem), normalise(title or '')):
        hits = [n for n in files if want and normalise(Path(n).stem) == want]
        if hits:
            break
    tags = _tags(stem)
    hits.sort(key=lambda n: (Path(n).stem != stem, -len(tags & _tags(Path(n).stem)), n))
    return [_rel(files[n]) for n in hits]


def _standalone_match(kind, name, serial, crc) -> bool:
    """The file names each emulator loads for a disc (§4.4)."""
    if kind == 'duckstation':
        return bool(serial) and name.endswith('.cht') and name.startswith(serial)
    return name.endswith('.pnach') and bool(
        (serial and crc and name.startswith(f'{serial}_{crc}')) or (crc and name.startswith(crc)))


# -----------------------------------------------------------------------------
# The player
# -----------------------------------------------------------------------------

def _player_source(game_id, candidates) -> Optional[str]:
    from services import player
    chosen = player._record(game_id).get('cheat_source')
    return chosen if chosen in candidates else (candidates[0] if candidates else None)


def _player_view(game, view) -> dict:
    from services import player
    if not cheats_folder(game['system_folder']):
        view['reason'] = str(_('The player has no cheats for this system.'))
        return view
    view['emulator'] = 'player'
    candidates = player_candidates(game['system_folder'], game['rom_path'], game.get('title'))
    view['candidates'] = [{'source': c, 'name': Path(c).stem} for c in candidates]
    view['source'] = _player_source(game['id'], candidates)
    own = player._game_file(game['id'], 'cht')
    path = own if own.is_file() else (store_dir() / view['source'] if view['source'] else None)
    if path is None:
        view['reason'] = str(_('No cheats were found for this game.'))
        return view
    view['cheats'] = [dict(c, locked=False) for c in parse_cht(_read_text(path))]
    return view


def _player_save(game, enabled, source) -> None:
    from services import player
    if not cheats_folder(game['system_folder']):
        raise CheatError(_('The player has no cheats for this system.'))
    candidates = player_candidates(game['system_folder'], game['rom_path'], game.get('title'))
    own = player._game_file(game['id'], 'cht')
    rec = player._record(game['id'])
    if source is not None:
        if source not in candidates:                       # INV-10
            raise CheatError(_("That cheat list is not one of this game's."))
        if source != rec.get('cheat_source') or not own.is_file():
            _copy(store_dir() / source, own)
            rec['cheat_source'] = source
            player._save_record(game['id'], rec)
    if not own.is_file():
        current = _player_source(game['id'], candidates)
        if current is None:
            raise CheatError(_('No cheats were found for this game.'))
        _copy(store_dir() / current, own)
        rec['cheat_source'] = current
        player._save_record(game['id'], rec)
    if enabled is not None:
        own.write_text(_set_cht(_read_text(own), set(enabled)), encoding='utf-8')


def place_for_launch(game_id, core, rom_path: Path, profile: Path) -> None:
    """Copy the game's list to <profile>/cheats/<library name>/<ROM
    basename>.cht, where RetroArch loads it, or remove a stale copy there
    (INV-1). Never raises: a cheat problem never stops a launch (INV-11)."""
    from services import player, player_cores
    try:
        library = player_cores.library_name(core)
        if not library:
            logger.warning("cheats: core %s has no library name; launching without cheats", core)
            return
        dest = profile / 'cheats' / library / f'{rom_path.stem}.cht'
        own = player._game_file(game_id, 'cht')
        if own.exists():
            _copy(own, dest)
        else:
            dest.unlink(missing_ok=True)
    except OSError as e:
        logger.warning("cheats: not set up for game %s, launching without them: %s", game_id, e)


def take_back(game_id, rom_path: Path, profile: Path) -> None:
    """After a session: RetroArch rewrote the launch copy with the in-game
    switches, so it replaces the game's list, then goes (INV-2)."""
    from services import player
    try:
        root = profile / 'cheats'
        copies = [sub / f'{rom_path.stem}.cht' for sub in root.iterdir()
                  if (sub / f'{rom_path.stem}.cht').is_file()] if root.is_dir() else []
        own = player._game_file(game_id, 'cht')
        if copies and own.is_file():
            _copy(max(copies, key=lambda p: p.stat().st_mtime), own)
        for p in copies:
            p.unlink()
    except OSError as e:
        logger.warning("cheats: in-game changes for game %s not kept: %s", game_id, e)


# -----------------------------------------------------------------------------
# DuckStation and PCSX2
# -----------------------------------------------------------------------------

def _emulator_cheats_dir(data_dir: Path, main_ini: str) -> Path:
    """`[Folders] Cheats` of the emulator's main settings, relative to its
    data folder, else `cheats`."""
    import configparser
    from services.emulator_adapters import _ini, _under
    value = 'cheats'
    try:
        if (data_dir / main_ini).is_file():
            value = _ini(data_dir / main_ini).get('Folders', 'Cheats', fallback='') or value
    except configparser.Error:
        pass
    return _under(data_dir, value)


def _standalone_state(ctx, kind) -> dict:
    """What the panel shows and a save writes, read from the emulator's
    files every time (INV-6)."""
    from services import standalone_settings as ss
    name, main_ini, flag_section = kind
    emu_dir = _emulator_cheats_dir(ctx['data_dir'], main_ini)
    store = {n: p for n, p in _store_files(name).items()
             if _standalone_match(name, n, ctx['serial'], ctx.get('crc'))}
    reads = dict(store)                  # the emulator's own file wins (INV-4)
    if emu_dir.is_dir():
        reads.update({p.name: p for p in emu_dir.iterdir()
                      if p.is_file() and _standalone_match(name, p.name, ctx['serial'], ctx.get('crc'))})
    names, always = [], False
    for n in sorted(reads):
        try:
            text = _read_text(reads[n])
        except (OSError, CheatError) as e:
            logger.warning("cheats: %s not read: %s", reads[n], e)
            continue
        names += [s for s in _sections(text) if s not in names]
        always = always or (name == 'pcsx2' and _ungrouped_patches(text))
    lines = ss._read_lines(ctx['file'])
    on = (ss.read_value(lines, {'section': flag_section, 'key': 'EnableCheats'}) or '').lower() == 'true'
    return {'emu_dir': emu_dir, 'store': store, 'names': names, 'always_on': always,
            'enabled': ss.read_values(lines, 'Cheats', 'Enable'), 'on': on, 'lines': lines}


def _standalone_save(ctx, kind, enabled) -> None:
    from services import standalone_settings as ss
    if not ctx.get('file'):
        raise CheatError(ctx.get('reason') or _('No cheats were found for this game.'))
    if enabled is None:
        raise CheatError(_('Send the names of the cheats to switch on.'))
    st = _standalone_state(ctx, kind)
    for name, path in st['store'].items():
        dest = st['emu_dir'] / name
        if not dest.exists():                # never the emulator's own file (INV-4)
            _copy(path, dest)
    listed = [n for n in st['names'] if n in enabled and '=' not in n]
    # A name RetroDB does not list (DuckStation's built-in cheats) stays on.
    names = listed + [n for n in st['enabled'] if n not in st['names']]
    lines = ss.write_values(st['lines'], 'Cheats', 'Enable', names)
    lines = ss.write_value(lines, {'section': kind[2], 'key': 'EnableCheats'},
                           'true' if names else 'false')
    ss.write_lines(ctx['file'], lines)


# -----------------------------------------------------------------------------
# Public
# -----------------------------------------------------------------------------

def game_view(game_id) -> Optional[dict]:
    """GET /api/games/<id>/cheats; None when the game is missing. `emulator`
    is None where the panel does not show."""
    from services import standalone_settings as ss
    ctx = ss._context(game_id)
    if not ctx.get('game'):
        return None
    view = {'emulator': None, 'candidates': [], 'source': None, 'cheats': [],
            'always_on': False, 'reason': None}
    emu = ctx.get('emulator') or {}
    if emu.get('is_player'):
        return _player_view(ctx['game'], view)
    kind = _STANDALONE.get(emu.get('binary_name'))
    if not kind:
        view['reason'] = str(_('Cheats work in the player, DuckStation and PCSX2.'))
        return view
    view['emulator'] = kind[0]
    if not ctx.get('file'):
        view['reason'] = str(ctx.get('reason') or _('No cheats were found for this game.'))
        return view
    st = _standalone_state(ctx, kind)
    view['always_on'] = st['always_on']
    view['cheats'] = [{'name': n, 'enabled': st['on'] and n in st['enabled'], 'locked': '=' in n}
                      for n in st['names']]
    if not st['names']:
        view['reason'] = str(_('No cheats were found for this game.'))
    return view


def save(game_id, enabled, source=None) -> None:
    """PUT /api/games/<id>/cheats: switch on exactly `enabled` (names);
    `source` picks the player's list, and with `enabled` None keeps that
    list's own switches. Raises CheatError."""
    from services import standalone_settings as ss
    ctx = ss._context(game_id)
    if not ctx.get('game'):
        raise CheatError(_('Game not found'))
    emu = ctx.get('emulator') or {}
    if emu.get('is_player'):
        return _player_save(ctx['game'], enabled, source)
    kind = _STANDALONE.get(emu.get('binary_name'))
    if not kind:
        raise CheatError(_('Cheats work in the player, DuckStation and PCSX2.'))
    return _standalone_save(ctx, kind, enabled)
