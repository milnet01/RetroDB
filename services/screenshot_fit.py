"""Is a screenshot true to its system? (PASS-59-161)

Fixed-palette machines only. Exact colour values cannot decide it: emulators
show the same machine in different colours, and stored shots are lossy and
upscaled. Two palette-free tests are used instead, keyed by systems.folder:

- At download, the original's exact colour count. Refuses only what is certain.
- For stored shots, how badly the picture fits the machine's colour count. A
  ranking for a person to judge, never a verdict: real shots with heavy dither
  score high too.
"""
import logging

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# Colours the machine shows at once; the stored-shot score fits to this many.
FIT_COLOURS = {'zxspectrum': 15, 'c64': 16, 'gb': 4}

# Above this many exact colours an original is not this machine. Twice the
# machine's own colours, leaving room for a captured border or a flicker blend;
# Game Boy allows a blend of each of its 4 shades with each other.
REFUSE_ABOVE = {'zxspectrum': 32, 'c64': 32, 'gb': 16}

# Larger than any of these machines' screens with border. A bigger original was
# scaled, and a scaling filter invents colours, so its count proves nothing.
_NATIVE_MAX_SIDE = 512

# JPEG and lossy WebP invent colours too, so only these formats can be counted.
_EXACT_FORMATS = {'PNG', 'GIF', 'BMP'}

_SCORE_MAX_SIDE = 480

# 8-bit and 16-bit systems (systems.folder). A game's versions on these look
# plainly different, so IGDB and RAWG shots, which are per game and not per
# version, count only for a game on one platform. Newer systems' versions look
# much alike and keep those shots: the user chose that trade on 2026-10-31,
# when the rule on every system left multi-platform games with 1 or 2 shots.
# Arcade folders are left out: their hardware spans generations.
EIGHT_AND_SIXTEEN_BIT = frozenset({
    # Nintendo
    'nes', 'famicom', 'fds', 'snes', 'sfc', 'snesna', 'gb', 'gbc', 'sgb', 'satellaview', 'sufami',
    # Sega
    'sg-1000', 'sc-3000', 'mark3', 'mastersystem', 'gamegear', 'genesis', 'megadrive', 'megadrivejp',
    'segacd', 'megacd', 'megacdjp',
    # NEC and SNK
    'pcengine', 'pcenginecd', 'supergrafx', 'tg16', 'tg-cd', 'pc88', 'pc98',
    'neogeo', 'neogeocd', 'neogeocdjp', 'ngp', 'ngpc',
    # Atari
    'atari2600', 'atari5200', 'atari7800', 'atari800', 'atarixe', 'atarilynx', 'atarist',
    # Commodore
    'c64', 'vic20', 'plus4', 'amiga', 'amiga600', 'amiga1200', 'cdtv',
    # Sinclair, Amstrad, Acorn, MSX and Apple
    'zxspectrum', 'zx81', 'zxnext', 'samcoupe', 'amstradcpc', 'gx4000', 'electron', 'bbcmicro',
    'msx', 'msx1', 'msx2', 'msxturbor', 'apple2', 'apple2gs',
    # Other home computers, consoles and handhelds
    'oric', 'coco', 'dragon32', 'trs-80', 'ti99', 'moto', 'to8', 'fm7', 'x1', 'x68000', 'spectravideo',
    'adam', 'colecovision', 'intellivision', 'channelf', 'odyssey2', 'videopac', 'astrocade', 'astrocde',
    'arcadia', 'crvision', 'scv', 'pv1000', 'multivision', 'gamate', 'gmaster', 'megaduck', 'supervision',
    'wonderswan', 'wonderswancolor',
})


def has_impossible_colours(path, folder):
    """True only when the original at `path` cannot be from system `folder`."""
    limit = REFUSE_ABOVE.get(folder)
    if limit is None:
        return False
    try:
        with Image.open(path) as im:
            if im.format not in _EXACT_FORMATS or max(im.size) > _NATIVE_MAX_SIDE:
                return False
            return im.convert('RGB').getcolors(limit) is None
    except (OSError, ValueError, Image.DecompressionBombError):
        return False  # not a readable image: the download's own checks handle it


def fit_error(path, colours):
    """Mean colour distance between a shot and its best `colours`-colour redraw.

    Higher is more suspicious. Raises OSError for an unreadable file."""
    with Image.open(path) as im:
        rgb = im.convert('RGB')
    rgb.thumbnail((_SCORE_MAX_SIDE, _SCORE_MAX_SIDE), Image.NEAREST)
    redrawn = rgb.quantize(colours, method=Image.Quantize.MEDIANCUT,
                           dither=Image.Dither.NONE).convert('RGB')
    difference = np.asarray(rgb, dtype=float) - np.asarray(redrawn, dtype=float)
    return float(np.sqrt((difference ** 2).sum(axis=2)).mean())
