"""PASS-59-155 INV-3 — every player core has a library name, and every
system's `cheats` folder is one the libretro cheat pack holds.
docs/specs/PASS-59-155-cheats.md §4.4.
"""
import json
from pathlib import Path

TABLE = json.loads((Path(__file__).resolve().parent.parent / 'data' / 'player_cores.json')
                   .read_text(encoding='utf-8'))

# The system folders of https://buildbot.libretro.com/assets/frontend/cheats.zip,
# listed 2026-10-29.
PACK_FOLDERS = {
    'Amstrad - GX4000', 'Atari - 2600', 'Atari - 5200', 'Atari - 7800',
    'Atari - 8-bit Family', 'Atari - Jaguar', 'Atari - Lynx', 'Bandai - WonderSwan',
    'Bandai - WonderSwan Color', 'ChaiLove', 'Coleco - ColecoVision', 'DOS',
    'FBNeo - Arcade Games', 'Mattel - Intellivision', 'Microsoft - MSX',
    'Microsoft - MSX2', 'NEC - PC Engine - TurboGrafx 16',
    'NEC - PC Engine CD - TurboGrafx-CD', 'NEC - PC Engine SuperGrafx', 'NEC - PC-FX',
    'Nintendo - Family Computer Disk System', 'Nintendo - Game Boy',
    'Nintendo - Game Boy Advance', 'Nintendo - Game Boy Color', 'Nintendo - Nintendo 64',
    'Nintendo - Nintendo 64 (Aleck64)', 'Nintendo - Nintendo 64 (Unreleased)',
    'Nintendo - Nintendo 64 (iQue)', 'Nintendo - Nintendo DS',
    'Nintendo - Nintendo Entertainment System', 'Nintendo - Satellaview',
    'Nintendo - Super Nintendo Entertainment System', 'Nintendo - Virtual Boy', 'PrBoom',
    'PuzzleScript', 'SNK - Neo Geo Pocket', 'SNK - Neo Geo Pocket Color', 'Sega - 32X',
    'Sega - Dreamcast', 'Sega - Game Gear', 'Sega - Master System - Mark III',
    'Sega - Mega Drive - Genesis', 'Sega - Mega-CD - Sega CD', 'Sega - SG-1000',
    'Sega - Saturn', 'Sinclair - ZX Spectrum +3', 'Sony - PlayStation',
    'Sony - PlayStation Portable', 'TIC-80', 'Thomson - MOTO', 'Wolfenstein 3D',
}


def _systems():
    return {k: v for k, v in TABLE.items() if not k.startswith('_')}


def test_inv3_every_core_has_a_library_name():
    cores = {c for e in _systems().values() for c in e.get('cores', [])}
    names = TABLE['_library_names']
    assert cores - set(names) == set()
    assert all(isinstance(names[c], str) and names[c].strip() for c in cores)


def test_inv3_every_cheats_folder_is_in_the_pack():
    folders = {k: e['cheats'] for k, e in _systems().items() if 'cheats' in e}
    assert folders, 'no system names a cheats folder'
    assert {k: f for k, f in folders.items() if f not in PACK_FOLDERS} == {}
