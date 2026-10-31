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
