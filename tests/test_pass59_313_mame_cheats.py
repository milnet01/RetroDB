"""PASS-59-313: MAME cheats from the imported cheat.7z collection.

The import unpacks the collection into the store; the game page lists a
set's cheats; MAME starts with its cheat plugin reading the same folder.
7-Zip is stood in for here, so the tests need no download.
"""

import zipfile
from pathlib import Path

import pytest

import config
from services import cheats, player_install

XML = """<mamecheat version="1">
  <cheat desc="Infinite Lives"><script state="run"><action>maincpu.pb@0000=03</action></script></cheat>
  <cheat desc=""><comment>separator</comment></cheat>
  <cheat desc="Invincibility"><script state="run"><action>maincpu.pb@0001=01</action></script></cheat>
</mamecheat>
"""


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BASE_DIR', str(tmp_path / 'app'))
    return tmp_path


@pytest.fixture
def fake_7zip(monkeypatch):
    """`7z x -o<out> <archive>` writes the sets named in the archive's text."""
    monkeypatch.setattr(player_install, 'host', lambda: 'linux')
    monkeypatch.setattr(player_install, '_seven_zip', lambda h, work: Path('/bin/7zz'))

    def run(argv, cwd=None):
        out = Path(next(a for a in argv if a.startswith('-o'))[2:])
        for name in Path(argv[-1]).read_text().split():
            (out / f'{name}.xml').write_text(XML)
    monkeypatch.setattr(player_install, '_run', run)


def _download_folder(root, sets, zipped=False):
    root.mkdir(parents=True)
    if zipped:
        with zipfile.ZipFile(root / 'cheat0264.zip', 'w') as zf:
            zf.writestr('cheat.7z', ' '.join(sets))
    else:
        (root / 'cheat.7z').write_text(' '.join(sets))
    return root


def test_import_unpacks_the_collection_and_lists_a_sets_cheats(store, fake_7zip):
    src = _download_folder(store / 'download', ['pacman', '10yard'])
    result = cheats.import_folder(src)
    assert result['copied']['mame'] == 2
    assert result['skipped'] == []
    assert cheats.mame_names('/roms/mame/10yard.zip') == ['Infinite Lives', 'Invincibility']
    assert cheats.mame_names('/roms/mame/galaga.zip') == []


def test_import_takes_cheat7z_out_of_the_downloaded_zip(store, fake_7zip):
    src = _download_folder(store / 'download', ['galaga'], zipped=True)
    assert cheats.import_folder(src)['copied']['mame'] == 1
    assert cheats.mame_names('galaga.zip') == ['Infinite Lives', 'Invincibility']


def test_a_new_import_replaces_the_collection_whole(store, fake_7zip):
    cheats.import_folder(_download_folder(store / 'old', ['pacman']))
    cheats.import_folder(_download_folder(store / 'new', ['galaga']))
    assert cheats.mame_names('pacman.zip') == []
    assert cheats.mame_names('galaga.zip')


def test_launch_args_only_once_a_collection_is_in(store, fake_7zip):
    assert cheats.mame_launch_args() == []
    cheats.import_folder(_download_folder(store / 'download', ['pacman']))
    assert cheats.mame_launch_args() == ['-plugin', 'cheat', '-cheatpath', str(cheats.mame_dir())]


def test_only_standalone_mame_counts_as_mame():
    assert cheats.is_mame({'binary_name': 'mame', 'is_retroarch': 0})
    assert not cheats.is_mame({'binary_name': 'retroarch', 'is_retroarch': 1})
    assert not cheats.is_mame(None)


def test_a_set_name_cannot_leave_the_cheat_folder(store, fake_7zip):
    cheats.import_folder(_download_folder(store / 'download', ['pacman']))
    assert cheats.mame_names('../../pacman') == cheats.mame_names('pacman.zip')
    assert cheats.mame_names('') == []
