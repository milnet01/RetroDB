"""Turnable 3D models of consoles and controllers for the museum (PASS-59-345).

static/models/hardware/models.json lists each <key>.glb beside it. A console
model names the system folders it shows; a controller model names part
numbers, matched as whole tokens in the controller's name, because the
controllers table's ids differ between installs and its names carry the
maker's part number ("DualShock (SCPH-1200)").

Every model is CC BY 4.0. A downloaded one carries its title, author and
Sketchfab page, and was changed here (cleaned, cut, shrunk); `ours` marks a
model made for RetroDB, which shows no maker's logo.
"""
import json
import os
import re
from functools import lru_cache

import config

MODEL_DIR = 'models/hardware'


@lru_cache(maxsize=1)
def _models():
    path = os.path.join(config.STATIC_PATH, MODEL_DIR, 'models.json')
    try:
        with open(path, encoding='utf-8') as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    return {key: {**entry, 'key': key, 'url': f'{MODEL_DIR}/{key}.glb'}
            for key, entry in raw.items()}


def for_system(folder):
    """The console model shown for a system folder, or None."""
    return next((m for m in _models().values() if folder in m.get('systems', ())), None)


def _has_part(name, part):
    # A part number stands alone: "3020" matches "(3020 / 3021)" but not "13020".
    return re.search(rf'(?<![A-Za-z0-9-]){re.escape(part)}(?![A-Za-z0-9-])', name) is not None


def for_controller(name):
    """The model shown for a controller, matched on its part number, or None."""
    return next((m for m in _models().values()
                 if any(_has_part(name or '', p) for p in m.get('controllers', ()))), None)
