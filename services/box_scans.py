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


def is_media_name(name):
    """Whether a stored scan's file name is a disc or cartridge picture."""
    return '_media_' in os.path.basename(name or '')


# A disc or cartridge scan sits on a plain backdrop (white, grey or black).
# A pixel within this much of the backdrop's colour, per channel, is backdrop.
_BACKDROP_TOLERANCE = 40
# How much of the picture's edge must be that colour for it to be a backdrop.
_BACKDROP_EDGE_SHARE = 0.9
# A crop this near square whose corners, outside the circle, are this much
# backdrop is a disc.
_DISC_ASPECT = (0.92, 1.08)
_DISC_CORNERS = 0.85
# A backdrop darker than this (its darkest channel) may match a black
# cartridge, so only a disc is cut from it.
_LIGHT_BACKDROP = 170
# A row or column whose object pixels are fewer than this share of the
# fullest one's is a speck on the scan, not the object.
_SPECK_SHARE = 0.03


def _backdrop(rgba):
    """(The backdrop pixels joined to the picture's edge, as a bool array,
    whether the backdrop is light), or None when the edge is not one plain
    colour."""
    import numpy as np
    rgb = rgba[..., :3].astype(np.int16)
    edge = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    colour = np.median(edge, axis=0)
    near = (np.abs(rgb - colour).max(axis=2) <= _BACKDROP_TOLERANCE) | (rgba[..., 3] < 16)
    edges = (near[0], near[-1], near[:, 0], near[:, -1])
    if np.concatenate(edges).mean() < _BACKDROP_EDGE_SHARE:
        return None
    # Spread in from the edge through backdrop pixels: straight runs along
    # each axis reach most of it, then one-pixel steps round the nooks.
    reached = np.zeros_like(near)
    reached[0], reached[-1], reached[:, 0], reached[:, -1] = edges
    while True:
        before = reached.copy()
        for axis in (0, 1):
            index = np.indices(near.shape)[axis]
            for flip in (False, True):
                def turn(a, axis=axis, flip=flip):
                    return np.flip(a, axis) if flip else a
                n, r, i = turn(near), turn(reached), turn(index)
                if flip:
                    i = i.max() - i
                # Reached when a reached pixel lies on this run of backdrop
                # behind it: none of the run broken since.
                last_break = np.maximum.accumulate(np.where(n, -1, i), axis=axis)
                last_reached = np.maximum.accumulate(np.where(r, i, -1), axis=axis)
                reached |= turn(n & (last_reached > last_break))
        grown = reached.copy()
        grown[1:] |= reached[:-1]
        grown[:-1] |= reached[1:]
        grown[:, 1:] |= reached[:, :-1]
        grown[:, :-1] |= reached[:, 1:]
        reached = grown & near
        if np.array_equal(reached, before):
            return reached, colour.min() >= _LIGHT_BACKDROP


def cut_out(path):
    """Take a disc or cartridge picture off its plain backdrop: the backdrop
    goes see-through and the picture is trimmed to the object, so the open
    box's disc fills its texture. A disc is cut to a circle, so a white label
    reaching its rim stays. Returns True when the file changed; a picture
    already cut, or one with no plain backdrop, is left alone."""
    import numpy as np
    from PIL import Image
    try:
        with Image.open(path) as image:
            rgba = np.array(image.convert('RGBA'))
    except Exception as e:  # noqa: BLE001 - an unreadable picture is left as it is
        logger.warning(f'Box scan {path!r} unreadable: {e}')
        return False
    found = _backdrop(rgba)
    if found is None:
        return False
    backdrop, light = found
    # A row or column holds the object when a share of it does; specks and
    # smudges on the scan would otherwise widen the trim off the disc.
    def holding(axis):
        counts = (~backdrop).sum(axis=axis)
        return np.flatnonzero(counts > max(2, _SPECK_SHARE * counts.max()))
    rows, cols = holding(1), holding(0)
    if len(rows) < 16 or len(cols) < 16:
        return False
    box = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1))
    crop, keep = rgba[box].copy(), ~backdrop[box]
    height, width = keep.shape
    y, x = np.ogrid[:height, :width]
    circle = ((2 * y + 1 - height) / height) ** 2 + ((2 * x + 1 - width) / width) ** 2 <= 1
    if (_DISC_ASPECT[0] <= width / height <= _DISC_ASPECT[1]
            and (~keep[~circle]).mean() >= _DISC_CORNERS):
        keep = circle
    elif not light:
        return False
    crop[..., 3] = np.where(keep, crop[..., 3], 0)
    if crop.shape == rgba.shape and np.array_equal(crop[..., 3], rgba[..., 3]):
        return False
    tmp = f'{path}.tmp'
    try:
        Image.fromarray(crop, 'RGBA').save(tmp, 'WEBP', quality=90)
        os.replace(tmp, path)
    except OSError as e:
        logger.warning(f'Could not cut out box scan {path!r}: {e}')
        if os.path.exists(tmp):
            os.remove(tmp)
        return False
    return True


def cut_out_stored(value):
    """Cut out every disc or cartridge picture a stored record names, passing
    over one whose corner is already see-through. Returns how many files
    changed."""
    from PIL import Image
    changed = 0
    for name in _files(value):
        path = _scan_path(name)
        if not (is_media_name(name) and path and os.path.isfile(path)):
            continue
        try:
            with Image.open(path) as image:
                if image.mode == 'RGBA' and image.getpixel((0, 0))[3] == 0:
                    continue
        except Exception:  # noqa: BLE001 - cut_out logs an unreadable picture
            pass
        changed += cut_out(path)
    return changed


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
        width, height = item.get('width'), item.get('height')
        if item['kind'] == 'media':
            media_from = source
            # Cutting it out trimmed the file, so the record's size is stale.
            from PIL import Image
            try:
                with Image.open(path) as image:
                    width, height = image.size
            except Exception:  # noqa: BLE001 - keep the recorded size
                pass
        found.append({'kind': item['kind'], 'caption': item.get('caption'),
                      'url': f"images/box_scans/{item['file']}",
                      'width': width, 'height': height})
    return found


def delete_scans_of(row):
    """Delete the scans of a games row just deleted or cleared."""
    if 'box_scans' in row.keys() and row['box_scans']:
        delete_scans(row['box_scans'])
