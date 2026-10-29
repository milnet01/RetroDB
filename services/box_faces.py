"""Slipcase box faces for a game (PASS-59-142).

An editor imports a Slipcase box file (`S.box.json`, format
`slipcase-box` version 1, Slipcase `docs/specs/SLIP-0104-turnable-3d-box.md`
§ 4.1) with its face pictures. The faces are stored as WebP in
`<IMAGE_PATH>/box_faces/` and described by the JSON in `games.box_faces`.
`boxart_3d` is never touched. Contract: `docs/specs/PASS-59-142-box-file-import.md`.
"""

import io
import json
import logging
import os
import re
import secrets

import config
from services.database import execute, query
from services.game_media_service import MAX_IMAGE_SIZE, _validate_image_bytes
from services.security import safe_path

logger = logging.getLogger(__name__)

FACES = ('front', 'spine', 'back', 'edge', 'top', 'bottom')
REQUIRED_FACES = ('front', 'spine')
COLOURS = ('top', 'bottom', 'edge')
SIZES = ('width_mm', 'height_mm', 'depth_mm')

MAX_BOX_FILE_SIZE = 64 * 1024
TARGET_HEIGHT = 1080          # the front's height after import; never enlarged
WEBP_QUALITY = 85             # services/image_utils.py stores WebP at 85
RECORD_VERSION = 1            # this record's own version, not the box file's

_COLOUR_RE = re.compile(r'^#[0-9A-Fa-f]{6}$')


class BoxImportError(Exception):
    """An import refused before anything was written. `code` is the stable
    reason the route and the page switch on; `detail` says which rule."""

    def __init__(self, code, detail=''):
        super().__init__(f'{code}: {detail}' if detail else code)
        self.code = code
        self.detail = detail


def faces_dir():
    return os.path.join(config.IMAGE_PATH, 'box_faces')


# ---------------------------------------------------------------------------
# Reading the stored record
# ---------------------------------------------------------------------------

def _stored_record(value):
    """The parsed games.box_faces value, or None when NULL or unreadable."""
    if not value:
        return None
    try:
        record = json.loads(value)
    except (TypeError, ValueError):
        return None
    if not isinstance(record, dict) or not isinstance(record.get('faces'), dict):
        return None
    return record


def _face_path(name):
    """Absolute path of a stored face, or None when the name would leave the
    faces folder or is a symlink (INV-5)."""
    if not isinstance(name, str) or not name:
        return None
    base = faces_dir()
    joined = os.path.join(base, name)
    # Before safe_path: it resolves a symlink to its target, so a link to
    # another file inside the folder would pass it.
    if os.path.islink(joined):
        return None
    return safe_path(joined, base)


def faces_for(game_row):
    """The game's stored box record with a `urls` map added, or None when it
    has none, it does not parse, or its front or spine file is missing."""
    try:
        value = game_row['box_faces']
    except (KeyError, IndexError):  # a dict / sqlite3.Row without the column
        value = None
    record = _stored_record(value)
    if record is None:
        return None
    faces = record['faces']
    for face in REQUIRED_FACES:
        path = _face_path(faces.get(face))
        if path is None or not os.path.isfile(path):
            return None
    record['urls'] = {
        face: f'images/box_faces/{faces[face]}' if faces.get(face) else None
        for face in FACES
    }
    return record


# ---------------------------------------------------------------------------
# Checking the box file (SLIP-0104 § 4.1's reading rules)
# ---------------------------------------------------------------------------

def _read(upload, limit):
    """The bytes of one upload, read only up to `limit` + 1 so an oversized
    file is detected without loading it whole. `upload` is bytes or a file
    object (a werkzeug FileStorage)."""
    if isinstance(upload, (bytes, bytearray)):
        return bytes(upload)
    stream = getattr(upload, 'stream', upload)
    return stream.read(limit + 1)


def _plain_name(name):
    return (isinstance(name, str) and name not in ('', '.', '..')
            and '/' not in name and '\\' not in name and not name.startswith('.'))


def _size(case, key):
    value = case.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 < value <= 1000:
        raise BoxImportError('bad_box_file', f'case.{key} is not a size above 0 and at most 1000')
    return value


def _section(data, key):
    value = data.get(key)
    if not isinstance(value, dict):
        raise BoxImportError('bad_box_file', f'{key} is missing')
    return value


def _parse_box_file(raw):
    """Check the description and return (case, colours, face names)."""
    if len(raw) > MAX_BOX_FILE_SIZE:
        raise BoxImportError('bad_json', 'the box file is larger than 64 KB')
    try:
        data = json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as e:
        raise BoxImportError('bad_json', str(e)) from e
    if not isinstance(data, dict):
        raise BoxImportError('bad_json', 'the box file is not a JSON object')
    if data.get('format') != 'slipcase-box':
        raise BoxImportError('bad_box_file', 'format is not slipcase-box')
    version = data.get('version')
    if type(version) is not int or version != 1:
        raise BoxImportError('bad_box_file', f'unsupported version {version!r}')

    case_in = _section(data, 'case')
    name = case_in.get('name')
    if not isinstance(name, str) or not name:
        raise BoxImportError('bad_box_file', 'case.name is not text')
    case = {'name': name, **{key: _size(case_in, key) for key in SIZES}}

    colours_in = _section(data, 'colours')
    colours = {}
    for key in COLOURS:
        value = colours_in.get(key)
        if not isinstance(value, str) or not _COLOUR_RE.match(value):
            raise BoxImportError('bad_box_file', f'colours.{key} is not #RRGGBB')
        colours[key] = value.upper()

    faces_in = _section(data, 'faces')
    for face in REQUIRED_FACES:
        if faces_in.get(face) is None:
            raise BoxImportError('bad_box_file', f'faces.{face} is null')
    names = {face: faces_in.get(face) for face in FACES}
    bad = [face for face, value in names.items() if value is not None and not _plain_name(value)]
    if bad:
        raise BoxImportError('bad_face_name', ', '.join(bad))
    return case, colours, names


# ---------------------------------------------------------------------------
# Converting the pictures
# ---------------------------------------------------------------------------

def _open_face(raw, face, edge_colour):
    """Decode one picture as RGB, flattening any transparency onto the edge
    colour as Slipcase does."""
    from PIL import Image
    if len(raw) > MAX_IMAGE_SIZE:
        raise BoxImportError('face_too_large', face)
    if not _validate_image_bytes(raw):
        raise BoxImportError('bad_image', face)
    try:
        with Image.open(io.BytesIO(raw)) as im:
            im.load()
            if im.mode in ('RGBA', 'LA') or (im.mode == 'P' and 'transparency' in im.info):
                rgba = im.convert('RGBA')
                flat = Image.new('RGB', rgba.size, edge_colour)
                flat.paste(rgba, mask=rgba.getchannel('A'))
                return flat
            return im.convert('RGB')
    except BoxImportError:
        raise
    except Exception as e:  # Pillow raises many types on a broken file
        raise BoxImportError('bad_image', face) from e


def _encode_faces(pictures, colours):
    """Scale every face by the one factor that brings the front to
    TARGET_HEIGHT (never enlarging), and encode each to WebP bytes."""
    from PIL import Image
    edge = colours['edge']
    images = {face: _open_face(raw, face, edge) for face, raw in pictures.items()}
    scale = min(1.0, TARGET_HEIGHT / images['front'].height)
    encoded = {}
    for face, im in images.items():
        if scale < 1.0:
            size = (max(1, round(im.width * scale)), max(1, round(im.height * scale)))
            im = im.resize(size, Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, 'WEBP', quality=WEBP_QUALITY)
        encoded[face] = buf.getvalue()
    return encoded


# ---------------------------------------------------------------------------
# Import and removal
# ---------------------------------------------------------------------------

def _delete_faces(record):
    """Delete the files a record names. Names outside the faces folder and
    symlinks are skipped and logged, never followed (INV-5)."""
    if not record:
        return
    for face in FACES:
        name = record.get('faces', {}).get(face)
        if not name:
            continue
        path = _face_path(name)
        if path is None:
            logger.warning(f'Box face {name!r} not deleted: outside {faces_dir()} or a symlink')
            continue
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
        except OSError as e:
            logger.warning(f'Could not delete box face {path}: {e}')


def import_box_file(game_id, uploads, replace=False):
    """Store the faces of the one `.box.json` among `uploads` (base name →
    bytes or file object) for `game_id`. Only the box file and the pictures
    it names are read, so the editor may pick a whole folder. Every check runs before anything is written; a
    failure raises BoxImportError and leaves disk and row unchanged.
    Returns the stored record as faces_for gives it."""
    box_files = [name for name in uploads if name.lower().endswith('.box.json')]
    if not box_files:
        raise BoxImportError('no_box_file')
    if len(box_files) > 1:
        raise BoxImportError('two_box_files', ', '.join(sorted(box_files)))
    case, colours, names = _parse_box_file(_read(uploads[box_files[0]], MAX_BOX_FILE_SIZE))

    missing = [names[face] for face in FACES if names[face] and names[face] not in uploads]
    if missing:
        raise BoxImportError('missing_face', ', '.join(missing))
    pictures = {face: _read(uploads[names[face]], MAX_IMAGE_SIZE)
                for face in FACES if names[face]}
    encoded = _encode_faces(pictures, colours)

    game = query('SELECT id, box_faces FROM games WHERE id = ?', (game_id,), one=True)
    if not game:
        raise BoxImportError('not_found')
    old = _stored_record(game['box_faces'])
    if faces_for(game) is not None and not replace:
        raise BoxImportError('exists')

    from services.atomic_io import atomic_write_bytes
    token = secrets.token_hex(4)
    stored = {face: None for face in FACES}
    written = []
    try:
        for face, data in encoded.items():
            filename = f'{game_id}_{face}_{token}.webp'
            path = os.path.join(faces_dir(), filename)
            os.makedirs(faces_dir(), exist_ok=True)
            atomic_write_bytes(path, data)
            written.append(path)
            stored[face] = filename
        record = {'version': RECORD_VERSION, 'case': case, 'colours': colours, 'faces': stored}
        execute('UPDATE games SET box_faces = ? WHERE id = ?', (json.dumps(record), game_id))
    except Exception as e:
        for path in written:
            try:
                os.remove(path)
            except OSError:
                pass
        logger.error(f'Box face import for game {game_id} failed while writing: {e}')
        raise BoxImportError('write_failed', str(e)) from e

    # Only now, with the row pointing at the new files, drop the old ones.
    # A failed delete leaks a file under a live game's prefix; it never
    # leaves the row naming a missing face.
    _delete_faces(old)
    logger.info(f'Imported box faces for game {game_id}: {", ".join(f for f in FACES if stored[f])}')
    return faces_for({'box_faces': json.dumps(record)})


def remove_box_faces(game_id):
    """Clear the game's faces: the column first, then the files. Returns
    whether there was a record to remove."""
    game = query('SELECT id, box_faces FROM games WHERE id = ?', (game_id,), one=True)
    if not game:
        raise BoxImportError('not_found')
    old = _stored_record(game['box_faces'])
    if game['box_faces'] is None:
        return False
    execute('UPDATE games SET box_faces = NULL WHERE id = ?', (game_id,))
    _delete_faces(old)
    return True
