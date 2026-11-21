# =============================================================================
# BOX SCANS (PASS-59-183)
# =============================================================================
# Every scan of one real release of a game, kept in games.box_scans for the 3D
# box (PASS-59-326) and the open box (PASS-59-325). One key per source; only
# MobyGames writes one so far. Files live in <IMAGE_PATH>/box_scans/, named
# <game_id>_<kind>_<n>_<token>.webp. A scrape writes the record
# (metadata_merger.apply_mobygames_to_metadata); this module chooses the cover
# group, and deletes files, never outside the folder.
# Spec: docs/specs/PASS-59-183-mobygames-source.md §4.5.
# =============================================================================

import json
import logging
import os

import config
from services.security import safe_path

logger = logging.getLogger(__name__)

VERSION = 1
MAX_ITEMS = 40

# MobyGames image type -> kind. An unknown type is kept as 'other'.
KINDS = {
    'Front Cover': 'front', 'Back Cover': 'back', 'Spine/Sides': 'spine',
    'Media': 'media', 'Manual': 'manual', 'Inside Cover': 'inside',
    'Full Cover': 'full', 'Extras': 'extras', 'Other': 'other',
}

# Packaging that is not a box on a shelf.
_NOT_A_BOX = ('Electronic', 'Promotional')

# MobyGames country codes that ScreenScraper spells otherwise.
_COUNTRY_CODES = {'es': 'sp', 'ww': 'wor'}


def scans_dir():
    return os.path.join(config.IMAGE_PATH, 'box_scans')


def kind_of(image):
    return KINDS.get(((image or {}).get('type') or {}).get('name'), 'other')


def packaging(group):
    """The cover group's packaging attribute ('Jewel Case', 'Box'...), or None."""
    for attribute in group.get('attributes') or []:
        if attribute.get('category') == 'Packaging':
            for value in attribute.get('attributes') or []:
                if value.get('name'):
                    return value['name']
    return None


def countries(group):
    return [c.get('country_code') for c in group.get('countries') or [] if c.get('country_code')]


def choose_group(covers, platform_id, own_region):
    """The one cover group to take scans from, or None (spec §4.5).

    A group for this platform that is a real box, nearest the game's region
    by ss_regions' order; on a tie the one with a spine scanned, then the one
    with more images, then the first listed.
    """
    from scraper.ss_regions import rank_order
    groups = [g for g in covers or []
              if any(p.get('id') == platform_id for p in g.get('platforms') or [])
              and packaging(g) not in _NOT_A_BOX and g.get('images')]
    if not groups:
        return None
    rank = rank_order(own_region)
    unranked = len(rank)

    def nearest(group):
        codes = [_COUNTRY_CODES.get(c, c) for c in countries(group)]
        return min((rank.get(c, unranked) for c in codes), default=unranked)

    def has_spine(group):
        return any(kind_of(i) == 'spine' for i in group['images'])

    return min(enumerate(groups),
               key=lambda ig: (nearest(ig[1]), not has_spine(ig[1]), -len(ig[1]['images']), ig[0]))[1]


def _scan_path(name):
    """Absolute path of a stored scan, or None when the name would leave the
    folder or is a symlink."""
    if not isinstance(name, str) or not name:
        return None
    base = scans_dir()
    joined = os.path.join(base, name)
    if os.path.islink(joined):
        return None
    return safe_path(joined, base)


def _files(value):
    """Every file name a stored record names; none for NULL or an unreadable one."""
    try:
        record = json.loads(value) if value else None
    except (TypeError, ValueError):
        return []
    if not isinstance(record, dict):
        return []
    names = []
    for source in record.values():
        if isinstance(source, dict):
            names.extend(i.get('file') for i in source.get('items') or [] if isinstance(i, dict))
    return [n for n in names if n]


def delete_scans(value, keep=()):
    """Delete the files a stored record names, except those in `keep`."""
    for name in _files(value):
        if name in keep:
            continue
        path = _scan_path(name)
        if path is None:
            logger.warning(f'Box scan {name!r} not deleted: outside {scans_dir()} or a symlink')
            continue
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f'Could not delete box scan {path}: {e}')


def drop_replaced(old_value, new_value):
    """After a Full Re-scrape wrote a new record, delete the old one's files.
    The orphan sweep keeps a live game's files, so nothing else would."""
    if old_value and new_value and old_value != new_value:
        delete_scans(old_value, keep=set(_files(new_value)))


def delete_scans_of(row):
    """Delete the scans of a games row just deleted or cleared."""
    if 'box_scans' in row.keys() and row['box_scans']:
        delete_scans(row['box_scans'])
