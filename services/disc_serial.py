# =============================================================================
# RETRODB - Disc serial reader (PASS-59-91 §4.6)
# =============================================================================
# Reads a PlayStation disc's serial (SLUS-01150) from the disc itself, and for
# PS2 the boot ELF's CRC, the two names DuckStation, PCSX2 and RPCS3 key their
# per-game settings files by. ISO9660 is walked through its directories, never
# grepped. Reads only; any failure gives ('', None).
# =============================================================================

from __future__ import annotations

import logging
import re
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_SECTOR = 2048
_RAW_SECTOR = 2352
_CHD_FRAME = 2448
_SYNC = b'\x00' + b'\xff' * 10 + b'\x00'
# User-data offset inside a CHD frame, by its first track's type.
_CHD_OFFSETS = {'MODE1': 0, 'MODE1_RAW': 16, 'MODE2_RAW': 24}
_BOOT_RE = re.compile(r'^\s*BOOT2?\s*=\s*(\S+)', re.IGNORECASE | re.MULTILINE)
_MAX_ELF = 64 * 1024 * 1024

SERIAL_RE = re.compile(r'^[A-Z]{4}-\d{5}$')
CRC_RE = re.compile(r'^[0-9A-F]{8}$')

# read(lba, count) -> count * 2048 bytes of user data
SectorReader = Callable[[int, int], bytes]


def _file_reader(path: Path, stride: int, offset: int) -> SectorReader:
    def read(lba, count):
        out = bytearray()
        with open(path, 'rb') as f:
            for n in range(lba, lba + count):
                f.seek(n * stride + offset)
                out += f.read(_SECTOR)
        return bytes(out)
    return read


def _image_reader(path: Path, mode_hint: Optional[str] = None) -> SectorReader:
    """A .iso or .bin: cooked 2048-byte sectors, or raw 2352-byte ones whose
    mode byte picks the user-data offset."""
    with open(path, 'rb') as f:
        head = f.read(16 * _RAW_SECTOR + 16)
    if head[:12] != _SYNC and not mode_hint:
        return _file_reader(path, _SECTOR, 0)
    mode = mode_hint or ('2' if len(head) > 16 * _RAW_SECTOR + 15
                         and head[16 * _RAW_SECTOR + 15] == 2 else '1')
    return _file_reader(path, _RAW_SECTOR, 24 if mode == '2' else 16)


def _cue_reader(cue: Path) -> Optional[SectorReader]:
    text = cue.read_text(errors='replace')
    file_m = re.search(r'^\s*FILE\s+"?(.+?)"?\s+BINARY', text, re.IGNORECASE | re.MULTILINE)
    track_m = re.search(r'^\s*TRACK\s+\d+\s+MODE([12])/(\d+)', text, re.IGNORECASE | re.MULTILINE)
    if not file_m or not track_m:
        return None
    data = cue.parent / file_m.group(1)
    if track_m.group(2) == '2048':
        return _file_reader(data, _SECTOR, 0)
    return _image_reader(data, track_m.group(1))


def _chd_reader(chd: Path) -> Optional[SectorReader]:
    chdman = shutil.which('chdman')
    if not chdman:
        return None
    info = subprocess.run([chdman, 'info', '-i', str(chd)], capture_output=True,
                          text=True, timeout=30, check=False).stdout
    m = re.search(r'TYPE:(\w+)', info)
    offset = _CHD_OFFSETS.get(m.group(1)) if m else None
    if offset is None:
        return None

    def read(lba, count):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'raw.bin'
            subprocess.run([chdman, 'extractraw', '-i', str(chd), '-o', str(out),
                            '--inputstartbyte', str(lba * _CHD_FRAME),
                            '--inputbytes', str(count * _CHD_FRAME), '-f'],
                           capture_output=True, timeout=60, check=False)
            raw = out.read_bytes() if out.exists() else b''
        return b''.join(raw[i * _CHD_FRAME + offset:i * _CHD_FRAME + offset + _SECTOR]
                        for i in range(count))
    return read


# -----------------------------------------------------------------------------
# ISO9660
# -----------------------------------------------------------------------------

def _records(read: SectorReader, lba: int, size: int):
    """(name, lba, size, is_dir) for each entry of a directory extent."""
    data = read(lba, max(1, -(-size // _SECTOR)))
    pos = 0
    while pos < min(len(data), size):
        length = data[pos]
        if length == 0:
            pos = (pos // _SECTOR + 1) * _SECTOR
            continue
        rec = data[pos:pos + length]
        name = rec[33:33 + rec[32]].decode('ascii', 'replace').split(';')[0]
        yield (name.upper(), struct.unpack_from('<I', rec, 2)[0],
               struct.unpack_from('<I', rec, 10)[0], bool(rec[25] & 2))
        pos += length


def _find(read: SectorReader, path: str):
    """(lba, size) of a file by its path from the root, or None."""
    pvd = read(16, 1)
    if pvd[1:6] != b'CD001':
        return None
    lba = struct.unpack_from('<I', pvd, 156 + 2)[0]
    size = struct.unpack_from('<I', pvd, 156 + 10)[0]
    parts = [p for p in re.split(r'[\\/]', path.upper()) if p]
    for i, part in enumerate(parts):
        hit = next((r for r in _records(read, lba, size) if r[0] == part), None)
        if not hit or hit[3] != (i < len(parts) - 1):
            return None
        lba, size = hit[1], hit[2]
    return lba, size


def _read_file(read: SectorReader, path: str) -> Optional[bytes]:
    found = _find(read, path)
    if not found or found[1] > _MAX_ELF:
        return None
    lba, size = found
    return read(lba, max(1, -(-size // _SECTOR)))[:size]


def _serial_from_boot(boot_name: str) -> str:
    """`SLUS_011.50` -> `SLUS-01150`; '' when it is not that shape."""
    name = boot_name.upper()
    digits = re.sub(r'\D', '', name[4:])
    serial = f'{name[:4]}-{digits}'
    return serial if SERIAL_RE.match(serial) else ''


def _ps2_crc(elf: bytes) -> str:
    crc = 0
    for (word,) in struct.iter_unpack('<I', elf[:len(elf) // 4 * 4]):
        crc ^= word
    return f'{crc:08X}'


def _from_iso(read: SectorReader, system_folder: str):
    cnf = _read_file(read, 'SYSTEM.CNF')
    if not cnf:
        return '', None
    m = _BOOT_RE.search(cnf.decode('ascii', 'replace'))
    if not m:
        return '', None
    boot_path = re.sub(r'^[a-z0-9]+:', '', m.group(1), flags=re.IGNORECASE).split(';')[0]
    serial = _serial_from_boot(re.split(r'[\\/]', boot_path)[-1])
    if not serial or system_folder != 'ps2':
        return serial, None
    elf = _read_file(read, boot_path)
    return serial, (_ps2_crc(elf) if elf else None)


def _sfb_title_id(data: bytes) -> str:
    """PS3_DISC.SFB's TITLE_ID entry: 16-byte key, big-endian offset, length."""
    if data[:4] != b'.SFB':
        return ''
    for pos in range(0x20, min(len(data), 0x200), 0x20):
        key = data[pos:pos + 16].rstrip(b'\x00')
        if key == b'TITLE_ID':
            off, length = struct.unpack_from('>II', data, pos + 16)
            value = data[off:off + length].rstrip(b'\x00').decode('ascii', 'replace')
            return value if SERIAL_RE.match(value) else ''
    return ''


def _sfo_title_id(data: bytes) -> str:
    """PARAM.SFO's TITLE_ID (`BLUS30443`) as `BLUS-30443`, or ''. A PSN or
    installed game folder has no PS3_DISC.SFB, only this file."""
    if data[:4] != b'\x00PSF' or len(data) < 0x14:
        return ''
    key_start, data_start, count = struct.unpack_from('<III', data, 0x08)
    for i in range(min(count, 256)):
        pos = 0x14 + i * 16
        if pos + 16 > len(data):
            break
        key_off, _fmt, length, _max, data_off = struct.unpack_from('<HHIII', data, pos)
        key_at = key_start + key_off
        key = data[key_at:data.find(b'\x00', key_at)]
        if key == b'TITLE_ID':
            value = data[data_start + data_off:data_start + data_off + length]
            return _dashed(value.rstrip(b'\x00').decode('ascii', 'replace'))
    return ''


_PS3_ID_RE = re.compile(r'(?<![A-Z0-9])([A-Z]{4})-?(\d{5})(?![0-9])')


def _dashed(title_id: str) -> str:
    """`BLUS30443` or `BLUS-30443` -> `BLUS-30443`; '' when neither."""
    m = _PS3_ID_RE.fullmatch(title_id.strip().upper())
    return f'{m.group(1)}-{m.group(2)}' if m else ''


def _ps3_folder_id(path: Path) -> str:
    sfb = path / 'PS3_DISC.SFB'
    if sfb.is_file():
        return _sfb_title_id(sfb.read_bytes())
    for sfo in (path / 'PS3_GAME' / 'PARAM.SFO', path / 'PARAM.SFO'):
        if sfo.is_file():
            return _sfo_title_id(sfo.read_bytes())
    return ''


def ps3_id_from_name(name: str) -> str:
    """A PS3 serial written in a file or folder name, as many dump sets do
    (`Demon's Souls [BLUS30443].iso`), as `BLUS-30443`; else ''."""
    m = _PS3_ID_RE.search(Path(name).name.upper())
    return f'{m.group(1)}-{m.group(2)}' if m else ''


# -----------------------------------------------------------------------------
# Public
# -----------------------------------------------------------------------------

def read_disc_ids(rom_path, system_folder: str) -> tuple:
    """(serial, crc). serial is 'AAAA-NNNNN' or ''. crc is 8 upper-case hex
    digits for ps2, else None. Raises nothing; any failure gives ('', None)."""
    try:
        path = Path(rom_path)
        if path.is_dir():
            return (_ps3_folder_id(path) or ps3_id_from_name(path.name)), None
        ext = path.suffix.lower()
        if ext == '.m3u':
            first = next((ln.strip() for ln in path.read_text(errors='replace').splitlines()
                          if ln.strip() and not ln.startswith('#')), '')
            return read_disc_ids(path.parent / first, system_folder) if first else ('', None)
        if ext == '.chd':
            reader = _chd_reader(path)
        elif ext == '.cue':
            reader = _cue_reader(path)
        elif ext in ('.iso', '.bin', '.img'):
            reader = _image_reader(path)
        else:
            return '', None
        if reader is None:
            return '', None
        if system_folder == 'ps3':
            sfb = _read_file(reader, 'PS3_DISC.SFB')
            return ((_sfb_title_id(sfb) if sfb else '') or ps3_id_from_name(path.name)), None
        return _from_iso(reader, system_folder)
    except Exception as e:  # noqa: BLE001 — the contract is "raises nothing"
        logger.info(f"disc serial: cannot read {rom_path}: {e}")
        return '', None
