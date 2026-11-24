# =============================================================================
# BUILT 3D BOXES (PASS-59-326)
# =============================================================================
# Builds a game's box_faces record from its scraped scans, on the real case for
# its console and region, with the face builders ported from Slipcase. A box
# imported from Slipcase is never written over. A build whose inputs have not
# changed writes nothing. Spec: docs/specs/PASS-59-326-auto-3d-box.md.
# =============================================================================

import hashlib
import json
import logging
import os

import config
from services import box_faces
from services.database import query
from services.security import safe_path

logger = logging.getLogger(__name__)

# Bump when a change here or in the port should rebuild every built box.
BUILD_VERSION = 4

# System folder -> Slipcase's platform name (spec §4.3). Any other folder
# gets no box: arcade sets and home computers came in boxes Slipcase has no
# case for.
PLATFORMS = {
    'psx': 'PS1', 'ps2': 'PS2', 'ps3': 'PS3', 'ps4': 'PS4', 'ps5': 'PS5',
    'psp': 'PSP', 'psvita': 'Vita',
    'xbox': 'Xbox', 'xbox360': 'Xbox 360', 'xboxone': 'Xbox One',
    'xboxseriesx': 'Xbox Series X',
    'gc': 'GameCube', 'wii': 'Wii', 'wiiu': 'Wii U', 'switch': 'Switch',
    'nes': 'NES', 'famicom': 'NES', 'snes': 'SNES', 'snesna': 'SNES', 'sfc': 'SNES',
    'n64': 'N64', 'gb': 'Game Boy', 'gbc': 'Game Boy Color', 'gba': 'GBA',
    'nds': 'DS', 'n3ds': '3DS',
    'genesis': 'Genesis', 'megadrive': 'Mega Drive', 'megadrivejp': 'Mega Drive',
    'mastersystem': 'Master System', 'gamegear': 'Game Gear', 'atari2600': 'Atari 2600',
    'tg16': 'TurboGrafx-16', 'pcengine': 'TurboGrafx-16',
    'saturn': 'Saturn', 'saturnjp': 'Saturn',
    'segacd': 'Sega CD', 'megacd': 'Sega CD', 'megacdjp': 'Sega CD',
    'dreamcast': 'Dreamcast',
    'pc': 'PC', 'dos': 'PC', 'windows': 'PC', 'windows3x': 'PC', 'windows9x': 'PC',
}

# Folders that name their region; the rest take it from the scans or the game.
_FOLDER_REGIONS = {'famicom': 'NTSC-J', 'sfc': 'NTSC-J', 'saturnjp': 'NTSC-J',
                   'megacdjp': 'NTSC-J', 'megadrivejp': 'NTSC-J', 'pcengine': 'NTSC-J',
                   'megacd': 'PAL'}

# Most PC games came in a large cardboard box, which Slipcase has no case for;
# only these packagings are built.
_PC_PACKAGING = {'Keep Case': 'PC DVD Case', 'Jewel Case': 'CD Jewel Case'}

# (platform, region) -> a tall box the scanned front's shape can pick over
# the usual case (PASS-59-329).
_TALL_BOXES = {('PS1', 'NTSC-U'): 'PS1 Long Box'}
# (platform, region) -> (first month, last month, case) for a case used only
# by games released in those months (PASS-59-329).
_DATED_CASES = {('NES', 'NTSC-U'): ('1985-10', '1987-09', 'NES Cartridge Box (hang tab)')}
# (platform, region or None for any, words) -> the case for a game whose
# Edition field holds those words (Slipcase's SLIP-0113 research; PASS-59-329).
# US Player's Choice GameCube games kept the black case.
_EDITION_CASES = (
    ('PS2', None, 'platinum', 'PS2 Platinum Case (PAL)'),
    ('PS3', None, 'greatest hits', 'PS3 Greatest Hits Case'),
    ('PS3', None, 'platinum', 'PS3 Platinum Case (PAL)'),
    ('PS4', None, 'playstation hits', 'PS4 PlayStation Hits Case'),
    ('Xbox', None, 'platinum hits', 'Xbox Platinum Hits Case'),
    ('Xbox 360', None, 'platinum hits', 'Xbox 360 Platinum Hits Case'),
    ('GameCube', 'PAL', "player's choice", "GameCube Player's Choice Case (PAL)"),
)
# (platform, region or None for any, title) -> the case every copy of that
# game came in (PASS-59-329, two sources each).
_TITLE_CASES = (
    ('Wii U', None, 'new super luigi u', 'Wii U Case (green)'),
    ('Wii U', 'NTSC-U', 'mario kart 8', 'Wii U Case (red)'),
    ('Wii U', 'NTSC-U', 'super mario maker', 'Wii U Case (red)'),
)
# PAL PS1 games on several discs came in the multiway case: two discs until
# G-Police (October 1997), three or more always (PSXPALDB; PASS-59-329).
_MULTIWAY = 'PS1 Multiway Case (PAL)'
_MULTIWAY_TWO_DISCS_UNTIL = '1997-10'

OUTCOMES = ('built', 'unchanged', 'imported', 'no_case', 'no_front', 'failed')


# ---------------------------------------------------------------------------
# Choosing the case
# ---------------------------------------------------------------------------

# PAL countries MobyGames names by codes ScreenScraper's Europe list lacks.
_MORE_PAL = ('au', 'nz', 'es', 'be', 'lu', 'at', 'ch', 'ie', 'ru', 'za')


def _region_of(code):
    """Slipcase's region for one country code (ScreenScraper's or MobyGames')."""
    from scraper.ss_regions import _EUROPE
    if code == 'jp':
        return 'NTSC-J'
    if code in _EUROPE or code in _MORE_PAL:
        return 'PAL'
    return 'NTSC-U'


def region_for(folder, countries, game_region):
    """The case region: the folder's own, else the scanned box's first country,
    else the game's region, else NTSC-U."""
    if folder in _FOLDER_REGIONS:
        return _FOLDER_REGIONS[folder]
    if countries:
        return _region_of(countries[0])
    from scraper.ss_regions import region_codes
    codes = region_codes(game_region)
    return _region_of(codes[0]) if codes else 'NTSC-U'


def case_for_game(folder, region, packaging=None, front_aspect=None, released=None,
                  discs=1, edition=None, title=None):
    """The case for a game, or None for no box (spec §4.3). `region` is
    Slipcase's (NTSC-U, PAL, NTSC-J); `packaging` the scans' MobyGames
    packaging, if any; `front_aspect` the scanned front's width / height,
    if known; `released` the game's `release_date`, if any; `discs` how
    many discs it has; `edition` and `title` the game's own fields."""
    from services.box3d import cases
    platform = PLATFORMS.get(folder)
    if platform is None:
        return None
    if platform == 'PC':
        name = _PC_PACKAGING.get(packaging)
        return cases.CASE_TYPES[name] if name else None
    case = cases.case_for(platform, region)
    if case is not None and packaging == 'Jewel Case' and case.layout != 'jewel':
        jewel = cases.CASE_TYPES['CD Jewel Case']
        # MobyGames also calls a tall Saturn or Sega CD box a jewel case;
        # the scanned front's shape says which it was.
        if front_aspect is None or _nearer(front_aspect, jewel, case):
            case = jewel
    tall = _TALL_BOXES.get((platform, region))
    if case is not None and tall and front_aspect is not None:
        if _nearer(front_aspect, cases.CASE_TYPES[tall], case):
            case = cases.CASE_TYPES[tall]
    dated = _DATED_CASES.get((platform, region))
    if dated and _released_within(released, dated[0], dated[1]):
        case = cases.CASE_TYPES[dated[2]]
    if (platform, region) == ('PS1', 'PAL') and case is not None and case.layout == 'jewel' and (
            discs >= 3 or (discs == 2 and released
                           and released[:7] <= _MULTIWAY_TWO_DISCS_UNTIL)):
        case = cases.CASE_TYPES[_MULTIWAY]
    words = (edition or '').casefold()
    for p, r, marker, name in _EDITION_CASES:
        if p == platform and r in (None, region) and marker in words:
            case = cases.CASE_TYPES[name]
            break
    name_of = (title or '').strip().casefold()
    for p, r, game, name in _TITLE_CASES:
        if p == platform and r in (None, region) and game == name_of:
            case = cases.CASE_TYPES[name]
            break
    return case


def case_choices(folder):
    """The cases a person may pick for a game in `folder`, in list order;
    empty where no box is built."""
    from services.box3d import cases
    platform = PLATFORMS.get(folder)
    if platform is None or platform == 'PC':
        return [] if platform is None else list(_PC_PACKAGING.values())
    return cases.cases_for_platform(platform)


def chosen_case(folder, name):
    """The case a person picked (`games.box_case`), or None for the
    builder's own choice. A name no longer offered counts as none."""
    from services.box3d import cases
    return cases.CASE_TYPES[name] if name and name in case_choices(folder) else None


def disc_count(rom_path):
    """How many discs a game has: the entries of its .m3u playlist, else 1."""
    if not rom_path or not rom_path.lower().endswith('.m3u'):
        return 1
    try:
        with open(rom_path, encoding='utf-8', errors='replace') as playlist:
            entries = [line for line in playlist
                       if line.strip() and not line.lstrip().startswith('#')]
    except OSError:
        return 1
    return max(1, len(entries))


def _released_within(released, first, last):
    """Whether a `release_date` (YYYY, YYYY-MM or YYYY-MM-DD) falls in the
    months `first` to `last` (YYYY-MM). A year alone counts only when all
    of it does."""
    if not released:
        return False
    if len(released) == 4:
        return first <= f'{released}-01' and f'{released}-12' <= last
    return first <= released[:7] <= last


def _nearer(aspect, case, other):
    """Whether `aspect` (width / height) is nearer `case`'s front than
    `other`'s, by ratio."""
    import math
    off = lambda c: abs(math.log(aspect * c.height / c.width))  # noqa: E731
    return off(case) <= off(other)


# ---------------------------------------------------------------------------
# Choosing the pictures
# ---------------------------------------------------------------------------

def _file(folder, name):
    """A stored picture's absolute path, or None when missing, a symlink or
    outside its folder."""
    if not isinstance(name, str) or not name.strip():
        return None
    base = os.path.join(config.IMAGE_PATH, folder)
    joined = os.path.join(base, os.path.basename(name.strip()))
    if os.path.islink(joined):  # before safe_path, which resolves links
        return None
    path = safe_path(joined, base)
    return path if path and os.path.isfile(path) else None


def _side_of(caption):
    """Which face a MobyGames Spine/Sides scan shows, by its caption."""
    words = (caption or '').lower()
    for side, face in (('right', 'edge'), ('top', 'top'), ('bottom', 'bottom')):
        if side in words:
            return face
    return 'spine'


def inputs(row):
    """Each face's source file and the scans' MobyGames facts (spec §4.2):
    {'front', 'full', 'back', 'spine', 'edge', 'top', 'bottom', 'box3d': path
     or None, 'packaging': str or None, 'countries': [codes]}. `box3d` is the
    downloaded 3D box picture, which shows the box as it looks (PASS-59-331)."""
    found = {face: None for face in ('front', 'full', 'back', 'spine', 'edge', 'top', 'bottom')}
    found.update(packaging=None, countries=[], box3d=_file('boxart_3d', row['boxart_3d']))
    try:
        record = json.loads(row['box_scans']) if row['box_scans'] else {}
    except (TypeError, ValueError):
        record = {}
    moby = record.get('mobygames') if isinstance(record, dict) else None
    if isinstance(moby, dict):
        found['packaging'] = moby.get('packaging')
        found['countries'] = [c for c in moby.get('countries') or [] if isinstance(c, str)]
        for item in moby.get('items') or []:
            if not isinstance(item, dict):
                continue
            kind = item.get('kind')
            face = _side_of(item.get('caption')) if kind == 'spine' else kind
            if face in found and found[face] is None:
                found[face] = _file('box_scans', item.get('file'))
    if found['front'] is None and found['full'] is None:
        found['front'] = _file('boxart', row['boxart'])
    if found['back'] is None:
        found['back'] = _file('boxart_back', row['boxart_back'])
    return found


def _signature(case, row, found):
    """What a build depends on, so an unchanged game is not rebuilt."""
    parts = [str(BUILD_VERSION), case.name, row['title'] or '', row['disc_serial'] or '']
    if case.shape is not None:
        # Left out when there is none, so a case without one keeps its old
        # signature; a new or changed shape rebuilds (it changes the faces).
        parts.append(repr(case.shape))
    for face in ('front', 'full', 'back', 'spine', 'edge', 'top', 'bottom', 'box3d'):
        path = found[face]
        parts.append(f'{face}={os.path.basename(path)}:{os.path.getsize(path)}' if path else f'{face}=')
    return hashlib.sha1('\n'.join(parts).encode('utf-8')).hexdigest()[:8]


def _open(path, height=box_faces.TARGET_HEIGHT):
    """One picture decoded as RGB, no more than twice `height` tall, so a
    large scan costs little memory (spec §4.2)."""
    from PIL import Image
    with Image.open(path) as im:
        im.draft('RGB', (im.width * 2 * height // max(1, im.height), 2 * height))
        im.load()
        factor = im.height // (2 * height)
        if factor > 1:
            im = im.reduce(factor)
        return im.convert('RGB')


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------

def _hex(rgb):
    return '#{:02X}{:02X}{:02X}'.format(*rgb)


def _front_aspect(found):
    """The scanned front's width / height, or None (a wrap, or unreadable)."""
    from PIL import Image
    if found['front'] is None:
        return None
    try:
        with Image.open(found['front']) as im:
            return im.width / max(1, im.height)
    except OSError:
        return None


def _faces(case, row, found, platform):
    """The built faces as PIL images, and the box model's colours.

    The downloaded 3D box picture shows the box as it looks (PASS-59-331):
    with no spine scan its spine is used, and when its front is another
    release's artwork, its front and spine both are. The back stays the
    scanned one, from whichever release it is.
    """
    from PIL import Image
    from services.box3d import cut3d, jewel
    from services.box3d.faces import build_box_model
    front = _open(found['front'] or found['full'])
    back = _open(found['back']) if found['back'] else None
    spine = _open(found['spine']) if found['spine'] else None
    if found['box3d'] and found['front']:  # a wrap carries its own spine
        cut = cut3d.cut_faces(found['box3d'], case, box_faces.TARGET_HEIGHT)
        if cut is not None:
            if cut3d.same_art(cut[0], front) < cut3d.SAME_ART:
                front, spine = cut
            elif spine is None:
                spine = cut[1]
    if back is not None and case.layout == 'jewel':
        case = jewel.card_case(back, platform, case)
    model = build_box_model(
        front, back, case, title=row['title'] or '', serial=row['disc_serial'] or '',
        platform=platform, spine_color=None, case_color=None,
        spine_left_offset=0, spine_right_offset=0,
        full_cover=None if found['front'] is None else False,
        show_texture=True, spine_image=spine)
    faces = {'front': model.front, 'spine': model.spine, 'back': model.back,
             'edge': model.edge_face, 'top': model.top_face, 'bottom': model.bottom_face}
    if case.texture == 'cardboard':
        # A cardboard box is printed all round; its scanned sides are its own.
        for face in ('edge', 'top', 'bottom'):
            if found[face]:
                side = _open(found[face])
                lying = face != 'edge'
                if (side.width > side.height) != lying:
                    side = side.transpose(Image.Transpose.ROTATE_270)
                size = ((model.front.width, max(1, round(case.depth * model.front.width / case.width)))
                        if lying else model.spine.size)
                faces[face] = side.resize(size, Image.LANCZOS)
    colours = {'top': _hex(model.top), 'bottom': _hex(model.bottom), 'edge': _hex(model.edge)}
    return case, faces, colours


def _shape(case):
    if case.shape is None:
        return None
    return {key: getattr(case.shape, key[:-3]) for key in box_faces.SHAPE_KEYS}


def _game(game_id):
    return query("""
        SELECT g.id, g.title, g.region, g.release_date, g.disc_serial, g.edition, g.rom_path,
               g.box_case, g.boxart, g.boxart_3d, g.boxart_back,
               g.box_scans, g.box_faces, s.folder
        FROM games g JOIN systems s ON s.id = g.system_id WHERE g.id = ?
    """, (game_id,), one=True)


def build_for_game(game_id):
    """Build the game's box from its scans when it has none, or a built one
    whose inputs changed. Returns one of OUTCOMES; never raises."""
    try:
        row = _game(game_id)
        if row is None:
            return 'failed'
        old = box_faces.stored_record(row['box_faces'])
        current = box_faces.faces_for(row)
        if current is not None and not box_faces.is_built(old):
            return 'imported'
        found = inputs(row)
        if found['front'] is None and found['full'] is None:
            return 'no_front'
        region = region_for(row['folder'], found['countries'], row['region'])
        case = chosen_case(row['folder'], row['box_case']) or case_for_game(
            row['folder'], region, found['packaging'], _front_aspect(found),
            row['release_date'], disc_count(row['rom_path']), row['edition'], row['title'])
        if case is None:
            return 'no_case'
        signature = _signature(case, row, found)
        if current is not None and old.get('inputs') == signature:
            return 'unchanged'

        case, faces, colours = _faces(case, row, found, PLATFORMS[row['folder']])
        encoded = {face: box_faces.to_webp(im) for face, im in faces.items() if im is not None}
        record = {'version': box_faces.RECORD_VERSION, 'source': box_faces.BUILT_SOURCE,
                  'inputs': signature, 'region': region,
                  'case': {'name': case.name, 'width_mm': case.width,
                           'height_mm': case.height, 'depth_mm': case.depth},
                  'colours': colours}
        shape = _shape(case)
        if shape is not None:
            record['shape'] = shape
        # Read again just before the write: an import may have landed while
        # the faces were drawn, and it always wins.
        latest = _game(game_id)
        if latest is None:
            return 'failed'
        if latest['box_faces'] != row['box_faces']:
            built = box_faces.is_built(box_faces.stored_record(latest['box_faces']))
            return 'unchanged' if built else 'imported'
        box_faces.store_faces(game_id, encoded, record, old)
        logger.info(f'Built a 3D box for game {game_id}: {case.name}')
        return 'built'
    except Exception as e:  # a build must never stop a scrape or the job
        logger.warning(f'Could not build a 3D box for game {game_id}: {e}')
        return 'failed'
