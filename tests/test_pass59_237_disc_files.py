"""PASS-59-237 — the ROM tools never delete, move or rename half a disc.

A .cue or .gdi names its track files and a .m3u names its discs, so a tool
that treats one of those files alone breaks the game. Audit 2026-11-04,
lanes 9 and 10.
"""
import os
import time

import pytest

from services import disc_files
from tests.test_pass59_rom_tools import rom_client  # noqa: F401
from tests._versions_util import vdb  # noqa: F401


def _cue(path, *tracks):
    path.write_text(''.join(f'FILE "{t}" BINARY\n  TRACK 01 MODE2/2352\n'
                            for t in tracks))
    for t in tracks:
        (path.parent / t).write_bytes(b'track ' + t.encode())
    return path


# --- services/disc_files ----------------------------------------------------

def test_sheet_tracks_reads_cue_and_gdi(tmp_path):
    cue = _cue(tmp_path / 'Game.cue', 'Game (Track 1).bin', 'Game (Track 2).bin')
    gdi = tmp_path / 'Disc.gdi'
    gdi.write_text('2\n1 0 4 2352 track01.bin 0\n2 600 0 2352 "track 02.raw" 0\n')
    assert disc_files.sheet_tracks(str(cue)) == [
        str(tmp_path / 'Game (Track 1).bin'), str(tmp_path / 'Game (Track 2).bin')]
    assert disc_files.sheet_tracks(str(gdi)) == [
        str(tmp_path / 'track01.bin'), str(tmp_path / 'track 02.raw')]


def test_playlists_follow_a_renamed_disc(tmp_path):
    folder = tmp_path / 'Game'
    folder.mkdir()
    disc = folder / 'Game (Disc 1).chd'
    disc.write_bytes(b'x')
    m3u = tmp_path / 'Game.m3u'
    m3u.write_text('Game/Game (Disc 1).chd\r\nGame/Game (Disc 2).chd\r\n')
    assert disc_files.playlists_naming(str(disc)) == [str(m3u)]
    disc_files.repoint_playlists(str(disc), str(folder / 'Game (Disc 1) [fixed].chd'))
    assert m3u.read_bytes() == (
        b'Game/Game (Disc 1) [fixed].chd\r\nGame/Game (Disc 2).chd\r\n')


# --- Duplicate Finder --------------------------------------------------------

@pytest.fixture
def dup_scan(rom_client, monkeypatch):  # noqa: F811
    import app as app_module
    import routes.tools as tools
    app_module.limiter.reset()
    post, roms = rom_client

    def run(method):
        resp = post('/api/rom-tools/duplicate-finder/scan',
                    {'path': str(roms), 'method': method})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
        task_id = resp.get_json()['task_id']
        for _ in range(200):
            if tools._rom_tool_tasks[task_id]['status'] != 'running':
                break
            time.sleep(0.02)
        return task_id, tools._rom_tool_tasks[task_id]['results']['groups']
    yield post, roms, run
    app_module.limiter.reset()


def test_name_mode_keeps_a_cue_and_its_bin_apart(dup_scan):
    _post, roms, run = dup_scan
    _cue(roms / 'Game.cue', 'Game.bin')
    assert run('name')[1] == []


def test_hash_mode_never_offers_a_track_two_sheets_share(dup_scan):
    _post, roms, run = dup_scan
    for name in ('Game (USA)', 'Game (USA) (Rev 1)'):
        _cue(roms / f'{name}.cue', f'{name} (Track 1).bin', 'Shared (Track 2).bin')
        (roms / f'{name} (Track 1).bin').write_bytes(name.encode())
    (roms / 'copy' ).mkdir()
    _cue(roms / 'copy' / 'Other.cue', 'Shared (Track 2).bin')
    groups = run('hash')[1]
    offered = {f['name'] for g in groups for f in g['files']}
    assert 'Shared (Track 2).bin' not in offered


def test_delete_moves_the_game_to_the_kept_copy(dup_scan, vdb):  # noqa: F811
    post, roms, run = dup_scan
    a, b = roms / 'Game (USA).sfc', roms / 'Game (Europe).sfc'
    for f in (a, b):
        f.write_bytes(b'same')
    gid = vdb.game('Game', rom_path=str(a))
    task_id, groups = run('hash')
    assert len(groups) == 1
    resp = post('/api/rom-tools/duplicate-finder/delete',
                {'task_id': task_id, 'files': [str(a)]})
    assert resp.get_json()['results']['deleted'] == 1
    row = vdb.conn.execute('SELECT rom_path FROM games WHERE id = ?', (gid,)).fetchone()
    assert row[0] == str(b)


def test_delete_keeps_a_disc_a_playlist_lists(dup_scan):
    post, roms, run = dup_scan
    (roms / 'Game').mkdir()
    listed = roms / 'Game' / 'Game (Disc 1).chd'
    loose = roms / 'Game (Disc 1).chd'
    for f in (listed, loose):
        f.write_bytes(b'same')
    (roms / 'Game.m3u').write_text('Game/Game (Disc 1).chd\n')
    task_id, _groups = run('hash')
    resp = post('/api/rom-tools/duplicate-finder/delete',
                {'task_id': task_id, 'files': [str(listed)]})
    assert resp.get_json()['results']['deleted'] == 0
    assert listed.exists()


# --- Organize Multi-Disc -----------------------------------------------------

def _organize(post, **body):
    return post('/api/reports/organize-multidisc', {'system': 'psx', **body})


@pytest.fixture
def psx(rom_client):  # noqa: F811
    post, roms = rom_client
    (roms / 'psx').mkdir()
    return post, roms / 'psx'


def test_organize_never_writes_over_a_playlist(psx):
    post, psx_dir = psx
    m3u = psx_dir / 'Game.m3u'
    m3u.write_text('hand edited\n')
    for n in (1, 2):
        (psx_dir / f'Game (Disc {n}).chd').write_bytes(b'x')
    resp = _organize(post, name='Game', files=['Game (Disc 1).chd', 'Game (Disc 2).chd'])
    assert resp.get_json()['success'] is False
    assert m3u.read_text() == 'hand edited\n'
    assert (psx_dir / 'Game (Disc 1).chd').exists()


def test_organize_never_writes_over_a_file_in_the_folder(psx):
    post, psx_dir = psx
    (psx_dir / 'Game').mkdir()
    there = psx_dir / 'Game' / 'Game (Disc 1).chd'
    there.write_bytes(b'already there')
    for n in (1, 2):
        (psx_dir / f'Game (Disc {n}).chd').write_bytes(b'loose')
    resp = _organize(post, name='Game', files=['Game (Disc 1).chd', 'Game (Disc 2).chd'])
    assert resp.get_json()['success'] is False
    assert there.read_bytes() == b'already there'
    assert (psx_dir / 'Game (Disc 2).chd').exists()


def test_organize_lists_sheets_not_their_tracks_and_moves_the_games(psx, vdb):  # noqa: F811
    post, psx_dir = psx
    names = []
    gids = []
    for n in (1, 2):
        cue = _cue(psx_dir / f'Game (Disc {n}).cue', f'Game (Disc {n}).bin')
        names += [cue.name, f'Game (Disc {n}).bin']
        gids.append(vdb.game(f'Game {n}', rom_path=str(cue)))
    resp = _organize(post, name='Game', files=names)
    assert resp.get_json()['success'] is True
    assert (psx_dir / 'Game.m3u').read_text() == (
        'Game/Game (Disc 1).cue\nGame/Game (Disc 2).cue\n')
    paths = [vdb.conn.execute('SELECT rom_path FROM games WHERE id = ?', (g,)).fetchone()[0]
             for g in gids]
    assert paths == [str(psx_dir / 'Game' / f'Game (Disc {n}).cue') for n in (1, 2)]


# --- CHD convert with delete originals --------------------------------------

def test_chd_delete_takes_the_tracks_but_not_a_shared_one(tmp_path, monkeypatch):
    from scraper.rom_tools import convert_one_to_chd
    from tests.test_pass59_119_rom_tools import _fake_chdman
    _fake_chdman(monkeypatch)
    cue = _cue(tmp_path / 'Game.cue', 'Game (Track 1).bin', 'Shared.bin')
    _cue(tmp_path / 'Game (Rev 1).cue', 'Game (Rev 1) (Track 1).bin', 'Shared.bin')
    (tmp_path / 'Game.m3u').write_text('Game.cue\n')
    result = convert_one_to_chd(str(cue), 'chdman', do_verify=True, delete_original=True)
    assert result['status'] == 'success'
    assert not cue.exists() and not (tmp_path / 'Game (Track 1).bin').exists()
    assert (tmp_path / 'Shared.bin').exists()
    assert (tmp_path / 'Game.m3u').read_text() == 'Game.chd\n'


def test_chd_route_moves_the_game_to_the_chd(rom_client, monkeypatch, vdb):  # noqa: F811
    import routes.tools as tools
    from tests.test_pass59_119_rom_tools import _fake_chdman, _inline_threads
    post, roms = rom_client
    monkeypatch.setattr(tools.shutil, 'which', lambda _p: '/usr/bin/chdman')
    _inline_threads(monkeypatch)
    _fake_chdman(monkeypatch)
    cue = _cue(roms / 'Game.cue', 'Game.bin')
    gid = vdb.game('Game', rom_path=str(cue))
    post('/api/rom-tools/chd-converter/convert',
         {'files': [str(cue)], 'delete_originals': True, 'verify': True})
    row = vdb.conn.execute('SELECT rom_path FROM games WHERE id = ?', (gid,)).fetchone()
    assert row[0] == str(roms / 'Game.chd')


# --- Archive Scanner: remove files reads names literally ---------------------

def _archive_stub(monkeypatch, before, after):
    import scraper.rom_tools as rt
    calls = []
    lists = iter([before, after])
    monkeypatch.setattr(rt.ArchiveScanner, '_list_archive_contents',
                        lambda self, _p: next(lists))
    monkeypatch.setattr(rt.subprocess, 'run', lambda cmd, **_k: calls.append(cmd) or
                        type('R', (), {'returncode': 0, 'stdout': '', 'stderr': ''})())
    return rt.ArchiveScanner(rt.ROMToolsConfig()), calls


def test_zip_removal_takes_names_literally(tmp_path, monkeypatch):
    scanner, calls = _archive_stub(monkeypatch, ['Game [!].sfc', 'Game [a].sfc', 'readme.txt'],
                                   ['Game [!].sfc', 'Game [a].sfc'])
    result = scanner.remove_files_from_archive(str(tmp_path / 'Game.zip'), ['readme.txt'])
    assert result['success'] is True
    assert '-nw' in calls[0]


def test_removal_that_took_more_than_asked_is_reported(tmp_path, monkeypatch):
    scanner, _calls = _archive_stub(monkeypatch, ['Game [!].sfc', 'Game [a].sfc'], [])
    result = scanner.remove_files_from_archive(str(tmp_path / 'Game.zip'), ['Game [!].sfc'])
    assert result['success'] is False
    assert 'Game [a].sfc' in result['error']


def test_7z_refuses_a_wildcard_name(tmp_path, monkeypatch):
    scanner, calls = _archive_stub(monkeypatch, ['a*.txt', 'ab.txt'], ['ab.txt'])
    result = scanner.remove_files_from_archive(str(tmp_path / 'Game.7z'), ['a*.txt'])
    assert result['success'] is False
    assert calls == []


# --- Rename: a track keeps its sheet, a disc keeps its playlist --------------

_RENAMES = {
    'reports': lambda post, gid: post('/api/reports/rename-rom',
                                      {'game_id': gid, 'new_name': 'Renamed (USA).bin'}),
    'scraped': lambda post, gid: post('/api/reports/rename-to-scraped', {'game_id': gid}),
    'game page': lambda post, gid: post(f'/api/rename-rom/{gid}',
                                        {'new_filename': 'Renamed (USA).bin'}),
}


@pytest.fixture
def psx_info(psx):
    post, psx_dir = psx
    (psx_dir / 'systeminfo.txt').write_text('Supported file extensions:\n.bin .cue .m3u\n')
    return post, psx_dir


@pytest.mark.parametrize('route', _RENAMES)
def test_rename_keeps_a_track_its_sheet_needs(psx_info, vdb, route):  # noqa: F811
    post, psx_dir = psx_info
    _cue(psx_dir / 'Game.cue', 'Game.bin')
    gid = vdb.game('Renamed', rom_path=str(psx_dir / 'Game.bin'))
    resp = _RENAMES[route](post, gid)
    assert resp.status_code == 400
    assert (psx_dir / 'Game.bin').exists()


@pytest.mark.parametrize('route', _RENAMES)
def test_rename_updates_the_playlist(psx_info, vdb, route):  # noqa: F811
    post, psx_dir = psx_info
    (psx_dir / 'Game').mkdir()
    disc = psx_dir / 'Game' / 'Game (Disc 1).bin'
    disc.write_bytes(b'x')
    m3u = psx_dir / 'Game.m3u'
    m3u.write_text('Game/Game (Disc 1).bin\nGame/Game (Disc 2).bin\n')
    gid = vdb.game('Renamed', rom_path=str(disc))
    resp = _RENAMES[route](post, gid)
    assert resp.status_code == 200, resp.get_json()
    new = vdb.conn.execute('SELECT rom_path FROM games WHERE id = ?', (gid,)).fetchone()[0]
    assert new != str(disc)
    assert m3u.read_text() == f'Game/{os.path.basename(new)}\nGame/Game (Disc 2).bin\n'


# --- Screenshot dedup: only files the scan grouped, one copy kept ------------

@pytest.fixture
def shots(rom_client, vdb, tmp_path, monkeypatch):  # noqa: F811
    import config
    import routes.tools as tools
    post, _roms = rom_client
    monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path / 'images'))
    folder = tmp_path / 'images' / 'screenshots'
    folder.mkdir(parents=True)
    for n in ('a.webp', 'b.webp', 'c.webp', 'other.webp'):
        (folder / n).write_bytes(b'x')
    gid = vdb.game('Game', screenshots='a.webp, b.webp, c.webp')
    task_id = 'shots-59237'
    tools._rom_tool_tasks[task_id] = {
        'task_id': task_id, 'task_type': 'screenshot_dedup', 'status': 'completed',
        'results': {'groups': [{'game_id': gid, 'duplicate_sets': [
            {'files': [{'filename': 'a.webp'}, {'filename': 'b.webp'}]}]}]},
        'logs': []}

    def delete(*names, task=task_id):
        return post('/api/rom-tools/screenshot-dedup/delete',
                    {'task_id': task,
                     'deletions': [{'game_id': gid, 'filename': n} for n in names]})
    yield delete, folder
    tools._rom_tool_tasks.pop(task_id, None)


def test_dedup_deletes_only_files_the_scan_grouped(shots):
    delete, folder = shots
    delete('c.webp', 'other.webp')
    assert (folder / 'c.webp').exists() and (folder / 'other.webp').exists()


def test_dedup_keeps_one_copy(shots):
    delete, folder = shots
    resp = delete('a.webp', 'b.webp')
    assert resp.status_code == 400
    assert (folder / 'a.webp').exists() and (folder / 'b.webp').exists()


def test_dedup_needs_the_scan(shots):
    delete, folder = shots
    resp = delete('a.webp', task='gone')
    assert resp.status_code == 400
    assert (folder / 'a.webp').exists()


def test_dedup_removes_a_spare_copy(shots):
    delete, folder = shots
    resp = delete('a.webp')
    assert resp.get_json()['results']['deleted'] == 1
    assert not (folder / 'a.webp').exists() and (folder / 'b.webp').exists()
