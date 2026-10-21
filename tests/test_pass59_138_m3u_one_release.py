# =============================================================================
# PASS-59-138 — Create M3U lists one release's disks, not every release's
# =============================================================================
# Some archives hold several releases of a game, each split into disks
# ("Game [Bonzai_Disk 1].d64", "Game [X-Ray_Disk 1].d64"). The playlist keeps
# the first release's disks; the rest stay in the folder and are reported.
# Names without a disk number on every file are listed as before.
# =============================================================================

import zipfile

import pytest

from scraper.rom_tools import ArchiveScanner, ROMToolsConfig


def _create(tmp_path, members):
    archive = tmp_path / 'Game.zip'
    with zipfile.ZipFile(archive, 'w') as zf:
        for name in members:
            zf.writestr(name, b'x')
    result = ArchiveScanner(ROMToolsConfig()).create_m3u_playlist(
        str(archive), move_to_staging=False)
    assert result['success'], result
    lines = (tmp_path / 'Game.m3u').read_text(encoding='utf-8').splitlines()
    return result, lines


def test_several_releases_keep_only_the_first(tmp_path):
    result, lines = _create(tmp_path, [
        'Game [X-Ray_Disk 2].d64', 'Game [Bonzai_Disk 1].d64',
        'Game [X-Ray_Disk 1].d64', 'Game [Bonzai_Disk 2].d64'])

    assert lines == ['Game/Game [Bonzai_Disk 1].d64', 'Game/Game [Bonzai_Disk 2].d64']
    assert result['skipped_files'] == ['Game [X-Ray_Disk 1].d64', 'Game [X-Ray_Disk 2].d64']


def test_one_release_lists_every_disk(tmp_path):
    result, lines = _create(tmp_path, ['Game (Disk 1 of 2).d64', 'Game (Disk 2 of 2).d64'])

    assert lines == ['Game/Game (Disk 1 of 2).d64', 'Game/Game (Disk 2 of 2).d64']
    assert result['skipped_files'] == []


# Both shapes are in the maintainer's library; neither is two releases.
@pytest.mark.parametrize('members', [
    ['Game (USA) (Disc 1) (Juice).chd', 'Game (USA) (Disc 2) (Mad Dog).chd'],
    [f'Game - Tape {t} - Side {s}.tzx' for t in (1, 2) for s in (1, 2)],
])
def test_subtitled_disks_and_tape_sides_stay_one_release(tmp_path, members):
    result, lines = _create(tmp_path, members)

    assert result['skipped_files'] == []
    assert len(lines) == len(members)


def test_files_without_disk_numbers_are_all_listed(tmp_path):
    _, lines = _create(tmp_path, ['Game - Boot.d64', 'Game - Data.d64'])

    assert lines == ['Game/Game - Boot.d64', 'Game/Game - Data.d64']
