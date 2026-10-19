"""PASS-59-91 INV-9, INV-10 — reading a disc's serial (and a PS2 boot CRC).

docs/specs/PASS-59-91-zero-setup-play.md §4.6 "Disc serial". Images are
built in tmp_path; `chdman` is a stub. No real disc image is read.
"""
import stat
import struct
import sys

from services.disc_serial import read_disc_ids

SECTOR = 2048


def _dir_record(name, lba, size, is_dir=False):
    ident = name.encode('ascii')
    length = 33 + len(ident) + (1 - len(ident) % 2)
    rec = bytearray(length)
    rec[0] = length
    rec[2:10] = struct.pack('<I', lba) + struct.pack('>I', lba)
    rec[10:18] = struct.pack('<I', size) + struct.pack('>I', size)
    rec[25] = 2 if is_dir else 0
    rec[32] = len(ident)
    rec[33:33 + len(ident)] = ident
    return bytes(rec)


def _iso(cnf_name='SYSTEM.CNF', boot=b'BOOT2 = cdrom0:\\SLUS_123.45;1\r\nVER = 1.00\r\n',
         elf=struct.pack('<II', 0x11111111, 0x22222222)):
    """A minimal ISO9660 image: PVD at 16, root directory at 18, then the
    SYSTEM.CNF and the boot ELF it names."""
    sectors = [bytes(SECTOR)] * 16
    root = _dir_record('\x00', 18, SECTOR, True) + _dir_record('\x01', 18, SECTOR, True)
    root += _dir_record(f'{cnf_name};1', 19, len(boot))
    root += _dir_record('SLUS_123.45;1', 20, len(elf))
    pvd = bytearray(SECTOR)
    pvd[0:7] = b'\x01CD001\x01'
    pvd[156:156 + 34] = _dir_record('\x00', 18, SECTOR, True)
    term = bytearray(SECTOR)
    term[0:7] = b'\xffCD001\x01'
    sectors += [bytes(pvd), bytes(term), root.ljust(SECTOR, b'\x00'),
                boot.ljust(SECTOR, b'\x00'), elf.ljust(SECTOR, b'\x00')]
    return sectors


def _write_iso(path, sectors):
    path.write_bytes(b''.join(sectors))
    return path


def test_inv9_iso_serial_and_ps2_crc(tmp_path):
    iso = _write_iso(tmp_path / 'game.iso', _iso())
    assert read_disc_ids(iso, 'ps2') == ('SLUS-12345', '33333333')


def test_inv9_ps1_gives_no_crc(tmp_path):
    iso = _write_iso(tmp_path / 'game.iso', _iso())
    assert read_disc_ids(iso, 'psx') == ('SLUS-12345', None)


def test_inv9_no_system_cnf_gives_nothing(tmp_path):
    iso = _write_iso(tmp_path / 'game.iso', _iso(cnf_name='OTHER.CNF'))
    assert read_disc_ids(iso, 'ps2') == ('', None)


def test_inv9_raw_bin_through_cue(tmp_path):
    raw = b''
    for data in _iso():
        frame = bytearray(2352)
        frame[1:11] = b'\xff' * 10
        frame[15] = 2
        frame[24:24 + SECTOR] = data
        raw += bytes(frame)
    (tmp_path / 'game.bin').write_bytes(raw)
    cue = tmp_path / 'game.cue'
    cue.write_text('FILE "game.bin" BINARY\n  TRACK 01 MODE2/2352\n    INDEX 01 00:00:00\n')
    assert read_disc_ids(cue, 'psx') == ('SLUS-12345', None)


def test_unknown_or_missing_file_gives_nothing(tmp_path):
    assert read_disc_ids(tmp_path / 'nope.iso', 'psx') == ('', None)
    (tmp_path / 'x.zip').write_bytes(b'PK')
    assert read_disc_ids(tmp_path / 'x.zip', 'psx') == ('', None)


def _stub_chdman(bin_dir):
    """`chdman info` prints the track type from <chd>.type; `extractraw`
    copies the asked byte range of the .chd file itself."""
    script = bin_dir / 'chdman'
    script.write_text(f'''#!{sys.executable}
import sys
args = sys.argv[1:]
opt = {{args[i]: args[i + 1] for i in range(1, len(args) - 1) if args[i].startswith('-')}}
src = opt['-i']
if args[0] == 'info':
    print('TRACK:1 TYPE:' + open(src + '.type').read().strip() + ' SUBTYPE:NONE FRAMES:21')
elif args[0] == 'extractraw':
    with open(src, 'rb') as f:
        f.seek(int(opt['--inputstartbyte']))
        data = f.read(int(opt['--inputbytes']))
    open(opt['-o'], 'wb').write(data)
''')
    script.chmod(script.stat().st_mode | stat.S_IXUSR)


def _write_chd(path, track_type, offset):
    raw = b''
    for data in _iso():
        frame = bytearray(2448)
        frame[offset:offset + SECTOR] = data
        raw += bytes(frame)
    path.write_bytes(raw)
    path.with_name(path.name + '.type').write_text(track_type)
    return path


def test_inv10_chd_offset_follows_track_type(tmp_path, monkeypatch):
    bin_dir = tmp_path / 'bin'
    bin_dir.mkdir()
    _stub_chdman(bin_dir)
    monkeypatch.setenv('PATH', str(bin_dir))
    mode1 = _write_chd(tmp_path / 'm1.chd', 'MODE1', 0)
    mode2 = _write_chd(tmp_path / 'm2.chd', 'MODE2_RAW', 24)
    assert read_disc_ids(mode1, 'ps2') == ('SLUS-12345', '33333333')
    assert read_disc_ids(mode2, 'ps2') == ('SLUS-12345', '33333333')


def test_inv10_no_chdman_gives_nothing(tmp_path, monkeypatch):
    chd = _write_chd(tmp_path / 'm1.chd', 'MODE1', 0)
    monkeypatch.setenv('PATH', str(tmp_path / 'empty'))
    assert read_disc_ids(chd, 'ps2') == ('', None)


def test_ps3_folder_reads_sfb_title_id(tmp_path):
    game = tmp_path / 'Game [BLUS31024]'
    game.mkdir()
    sfb = bytearray(0x200)
    sfb[0:4] = b'.SFB'
    entry = b'TITLE_ID'.ljust(16, b'\x00') + struct.pack('>II', 0x100, 10)
    sfb[0x20:0x20 + len(entry)] = entry
    sfb[0x100:0x10A] = b'BLUS-31024'
    (game / 'PS3_DISC.SFB').write_bytes(bytes(sfb))
    assert read_disc_ids(game, 'ps3') == ('BLUS-31024', None)
