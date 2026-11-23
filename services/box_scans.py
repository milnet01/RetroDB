# =============================================================================
# BOX SCANS (PASS-59-183)
# =============================================================================
# Every scan of one real release of a game, kept in games.box_scans for the 3D
# box (PASS-59-326) and the open box (PASS-59-325). One key per source:
# MobyGames' cover group, and the disc or cartridge picture of ScreenScraper or
# ES-DE where no source has one yet (PASS-59-328). Files live in
# <IMAGE_PATH>/box_scans/, named
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
    """The one cover group to take scans from, or None (spec §4.5): the
    first of ranked_groups."""
    groups = ranked_groups(covers, platform_id, own_region)
    return groups[0] if groups else None


def ranked_groups(covers, platform_id, own_region):
    """The cover groups for this platform that are a real box, best first:
    nearest the game's region by ss_regions' order; on a tie the one with a
    spine scanned, then the one with more images, then the first listed.
    """
    from scraper.ss_regions import rank_order
    groups = [g for g in covers or []
              if any(p.get('id') == platform_id for p in g.get('platforms') or [])
              and packaging(g) not in _NOT_A_BOX and g.get('images')]
    if not groups:
        return []
    rank = rank_order(own_region)
    unranked = len(rank)

    def nearest(group):
        codes = [_COUNTRY_CODES.get(c, c) for c in countries(group)]
        return min((rank.get(c, unranked) for c in codes), default=unranked)

    def has_spine(group):
        return any(kind_of(i) == 'spine' for i in group['images'])

    order = sorted(enumerate(groups),
                   key=lambda ig: (nearest(ig[1]), not has_spine(ig[1]), -len(ig[1]['images']), ig[0]))
    return [group for _i, group in order]


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


# Sources in the order the open box takes their pictures: MobyGames' scans are
# of one real release, so its disc wins over a picture from another source.
SOURCES = ('mobygames', 'screenscraper', 'esde')


def _record(value):
    """A stored record as a dict; {} for NULL or an unreadable one."""
    try:
        record = json.loads(value) if value else None
    except (TypeError, ValueError):
        return {}
    return record if isinstance(record, dict) else {}


def _sourced_items(value):
    """(source, item) for every item of a stored record, MobyGames' first,
    then each other source in SOURCES order, then any unknown one."""
    record = _record(value)
    order = sorted(record, key=lambda k: SOURCES.index(k) if k in SOURCES else len(SOURCES))
    return [(key, i) for key in order if isinstance(record[key], dict)
            for i in record[key].get('items') or [] if isinstance(i, dict)]


def _items(value):
    return [item for _source, item in _sourced_items(value)]


def has_source(value, source):
    return isinstance(_record(value).get(source), dict)


def has_kind(value, kind):
    return any(i.get('kind') == kind for i in _items(value))


def with_source(value, source, entry):
    """The stored record with `source`'s entry added, as JSON. A record that
    already holds that source is returned unchanged: box_scans is fill-only
    per source, so a new source merges into a row another one filled."""
    record = _record(value)
    if isinstance(record.get(source), dict):
        return value
    record.setdefault('version', VERSION)
    record[source] = entry
    return json.dumps(record)


def media_name(game_id, token):
    """The file name of a source's one disc or cartridge picture."""
    return f'{game_id}_media_0_{token}.webp'


def media_entry(name):
    """A source entry holding one stored disc or cartridge picture, with its
    size read from the file's header; None, and the file deleted, when it is
    unreadable."""
    from PIL import Image
    path = _scan_path(name)
    if path is None:
        return None
    try:
        with Image.open(path) as image:
            width, height = image.size
    except Exception as e:  # noqa: BLE001 - any unreadable picture is skipped
        logger.warning(f'Box scan {name!r} unreadable: {e}')
        _delete_files([name])
        return None
    return {'items': [{'kind': 'media', 'caption': None, 'file': name,
                       'width': width, 'height': height}]}


def _files(value):
    """Every file name a stored record names."""
    return [i['file'] for i in _items(value) if i.get('file')]


def delete_scans(value, keep=()):
    """Delete the files a stored record names, except those in `keep`."""
    _delete_files(name for name in _files(value) if name not in keep)


def _delete_files(names):
    for name in names:
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


# What the open box (PASS-59-325) shows inside: the disc or cartridge, the
# manual and leaflets. The outside of the box is box_faces' job.
INSIDE_KINDS = ('media', 'manual', 'inside', 'extras', 'other')


def scans_for(game_row):
    """The scans the open box shows, MobyGames' first, as
    [{kind, caption, url, width, height}], only those whose file is on disk."""
    try:
        value = game_row['box_scans']
    except (KeyError, IndexError):  # a row without the column
        return []
    found, media_from = [], None
    for source, item in _sourced_items(value):
        if item.get('kind') not in INSIDE_KINDS:
            continue
        # One disc: from the first source that has one on disk.
        if item['kind'] == 'media' and media_from not in (None, source):
            continue
        path = _scan_path(item.get('file'))
        if path is None or not os.path.isfile(path):
            continue
        if item['kind'] == 'media':
            media_from = source
        found.append({'kind': item['kind'], 'caption': item.get('caption'),
                      'url': f"images/box_scans/{item['file']}",
                      'width': item.get('width'), 'height': item.get('height')})
    return found


def delete_scans_of(row):
    """Delete the scans of a games row just deleted or cleared."""
    if 'box_scans' in row.keys() and row['box_scans']:
        delete_scans(row['box_scans'])
