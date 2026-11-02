# =============================================================================
# RETRODB - What file is this? (PASS-59-217)
# =============================================================================
# The name, size and CRC of the game inside a ROM file, which ScreenScraper can
# recognise. A zip's CRC comes from its own directory, so nothing is unpacked
# and no member name reaches the filesystem. Reads only; any failure gives None.
# =============================================================================

import hashlib
import logging
import os
import zipfile
import zlib

logger = logging.getLogger(__name__)

MAX_PLAIN_FILE = 1024 ** 3
MAX_MD5_FILE = 64 * 1024 * 1024
_READ_SIZE = 1024 * 1024
_NOT_THE_GAME = ('/', '.txt', '.nfo', '.diz')
# Containers and playlists: their own CRC is one nobody else holds.
_NO_USEFUL_CRC = {'.chd', '.rvz', '.wux', '.m3u', '.ps3', '.ps4', '.7z'}


def file_identity(rom_path):
    """{'name', 'size', 'crc'} of the game inside rom_path, or None."""
    try:
        extension = os.path.splitext(rom_path)[1].lower()
        if not os.path.isfile(rom_path) or extension in _NO_USEFUL_CRC:
            return None
        return _zip_identity(rom_path) if extension == '.zip' else _plain_identity(rom_path)
    except (OSError, ValueError, zipfile.BadZipFile) as e:
        logger.debug(f"Could not read {rom_path}: {e}")
        return None


def file_md5(rom_path, limit=MAX_MD5_FILE):
    """MD5 of the game inside rom_path, which means reading all of it, or None.
    Over `limit` bytes gives None. Nothing is written to disk."""
    try:
        identity = file_identity(rom_path)
        if not identity or identity['size'] > limit:
            return None
        digest = hashlib.md5(usedforsecurity=False)
        if os.path.splitext(rom_path)[1].lower() == '.zip':
            with zipfile.ZipFile(rom_path) as archive, archive.open(identity['name']) as member:
                _read_into(digest, member)
        else:
            with open(rom_path, 'rb') as f:
                _read_into(digest, f)
        return digest.hexdigest()
    except (OSError, ValueError, RuntimeError, EOFError, zipfile.BadZipFile, zlib.error) as e:
        logger.debug(f"Could not read {rom_path}: {e}")
        return None


def _read_into(digest, stream):
    for chunk in iter(lambda: stream.read(_READ_SIZE), b''):
        digest.update(chunk)


def _zip_identity(rom_path):
    with zipfile.ZipFile(rom_path) as archive:
        members = [m for m in archive.infolist()
                   if not m.filename.lower().endswith(_NOT_THE_GAME)]
    if len(members) != 1:
        return None  # Empty, or a set such as an arcade game's: no one file is the game.
    return {'name': members[0].filename, 'size': members[0].file_size,
            'crc': format(members[0].CRC, '08X')}


def _plain_identity(rom_path):
    size = os.path.getsize(rom_path)
    if size > MAX_PLAIN_FILE:
        return None
    crc = 0
    with open(rom_path, 'rb') as f:
        for chunk in iter(lambda: f.read(_READ_SIZE), b''):
            crc = zlib.crc32(chunk, crc)
    return {'name': os.path.basename(rom_path), 'size': size, 'crc': format(crc, '08X')}
