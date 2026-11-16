"""PASS-59-313: MAME cheats from the imported cheat.7z collection.

The import copies cheat.7z into the store unopened (MAME reads it packed)
and saves each arcade set's cheat names for the game page; MAME starts with
its cheat plugin reading the same folder. A stand-in for 7-Zip answers the
two commands the import runs, so the tests need no download.
"""

import json
import os
import sys
import zipfile
from pathlib import Path

import pytest

import config
from services import cheats, player_install

XML = """<mamecheat version="1">
  <cheat desc="Infinite Lives"><script state="run"><action>maincpu.pb@0000=03</action></script></cheat>
  <cheat desc=""><comment>separator</comment></cheat>
  <cheat desc="Invincibility"><script state="run"><action>maincpu.pb@0001=01</action></script></cheat>
  <cheat desc="Infinite Lives"><comment>same name twice</comment></cheat>
</mamecheat>
"""

# The stand-in's archive is JSON {path: text}. `l -slt -ba` lists each file
# as 7-Zip does; `x -so` writes their bytes back to back, in that order.
FAKE_7ZZ = """
import json, sys
files = json.load(open(sys.argv[-1]))
if sys.argv[1] == 'l':
    print('Path = cpc_flop\\nFolder = +\\nSize = 0\\n')
    for path, text in files.items():
        print(f"Path = {path}\\nFolder = -\\nSize = {len(text.encode())}\\n")
else:
    for text in files.values():
        sys.stdout.buffer.write(text.encode())
"""


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'BASE_DIR', str(tmp_path / 'app'))
    return tmp_path


@pytest.fixture
def fake_7zip(tmp_path, monkeypatch):
    tool = tmp_path / 'tools' / '7zz'
    tool.parent.mkdir()
    tool.write_text(f'#!{sys.executable}\n{FAKE_7ZZ}')
    tool.chmod(0o755)
    monkeypatch.setattr(player_install, 'host', lambda: 'linux')
    monkeypatch.setattr(player_install, '_seven_zip', lambda h, work: tool)


def _download_folder(root, sets, zipped=False, extra=None):
    files = {f'{name}.xml': XML for name in sets}
    files.update(extra or {})
    root.mkdir(parents=True)
    body = json.dumps(files)
    if zipped:
        with zipfile.ZipFile(root / 'cheat0264.zip', 'w') as zf:
            zf.writestr('cheat.7z', body)
    else:
        (root / 'cheat.7z').write_text(body)
    return root


def test_import_keeps_the_archive_packed_and_lists_a_sets_cheats(store, fake_7zip):
    src = _download_folder(store / 'download', ['pacman', '10yard'])
    result = cheats.import_folder(src)
    assert result['copied']['mame'] == 2
    assert result['skipped'] == []
    assert (cheats.mame_dir() / 'cheat.7z').read_bytes() == (src / 'cheat.7z').read_bytes()
    assert not (cheats.mame_dir() / 'cheat').exists()
    assert sorted(p.name for p in cheats.mame_dir().iterdir()) == ['cheat.7z', 'names.sqlite3']
    assert cheats.mame_names('/roms/mame/10yard.zip') == ['Infinite Lives', 'Invincibility']
    assert cheats.mame_names('/roms/mame/galaga.zip') == []


def test_names_are_read_as_xml_and_software_lists_are_passed_over(store, fake_7zip):
    extra = {
        'qbert.xml': '<mamecheat><cheat desc="Lives &amp; Time"/></mamecheat>',
        'cpc_flop/qbert.xml': XML,
        'broken.xml': '<mamecheat><cheat desc="x"',
        'dino.json': '{"desc": "not read"}',
    }
    result = cheats.import_folder(_download_folder(store / 'download', ['galaga'], extra=extra))
    assert result['copied']['mame'] == 2
    assert cheats.mame_names('qbert.zip') == ['Lives & Time']
    assert cheats.mame_names('broken.zip') == []
    assert cheats.mame_names('galaga.zip') == ['Infinite Lives', 'Invincibility']


def test_import_takes_cheat7z_out_of_the_downloaded_zip(store, fake_7zip):
    src = _download_folder(store / 'download', ['galaga'], zipped=True)
    assert cheats.import_folder(src)['copied']['mame'] == 1
    assert cheats.mame_names('galaga.zip') == ['Infinite Lives', 'Invincibility']


def test_a_new_import_replaces_the_collection_whole(store, fake_7zip):
    cheats.import_folder(_download_folder(store / 'old', ['pacman']))
    cheats.import_folder(_download_folder(store / 'new', ['galaga']))
    assert cheats.mame_names('pacman.zip') == []
    assert cheats.mame_names('galaga.zip')
    assert [p.name for p in cheats.mame_dir().iterdir() if p.name.startswith('.import-')] == []


def test_an_archive_with_no_cheats_leaves_the_old_collection(store, fake_7zip):
    cheats.import_folder(_download_folder(store / 'old', ['pacman']))
    result = cheats.import_folder(_download_folder(store / 'new', [], extra={'cpc_flop/x.xml': XML}))
    assert result['copied']['mame'] == 0
    assert result['skipped'][0]['reason'] == 'cheat.7z holds no MAME cheat files.'
    assert cheats.mame_names('pacman.zip')


def test_launch_args_only_once_a_collection_is_in(store, fake_7zip):
    assert cheats.mame_launch_args() == []
    cheats.import_folder(_download_folder(store / 'download', ['pacman']))
    assert cheats.mame_launch_args()[:4] == ['-plugin', 'cheat', '-cheatpath', str(cheats.mame_dir())]


def test_only_standalone_mame_counts_as_mame():
    assert cheats.is_mame({'binary_name': 'mame', 'is_retroarch': 0})
    assert not cheats.is_mame({'binary_name': 'retroarch', 'is_retroarch': 1})
    assert not cheats.is_mame(None)


def test_a_rom_path_is_looked_up_by_its_set_name_only(store, fake_7zip):
    cheats.import_folder(_download_folder(store / 'download', ['pacman']))
    assert cheats.mame_names('../../pacman') == cheats.mame_names('pacman.zip')
    assert cheats.mame_names('') == []
    assert cheats.mame_names(None) == []


@pytest.mark.skipif(not os.access('/usr/bin/7zz', os.X_OK), reason='needs a real 7-Zip')
def test_a_real_archive_reads_the_same(store, tmp_path, monkeypatch):
    """The stand-in's output matches real 7-Zip's: build a real .7z."""
    import subprocess
    src = tmp_path / 'src'
    src.mkdir()
    (src / 'pacman.xml').write_text(XML)
    (src / 'nes').mkdir()
    (src / 'nes' / 'smb.xml').write_text(XML)
    root = tmp_path / 'download'
    root.mkdir()
    subprocess.run(['/usr/bin/7zz', 'a', '-bd', str(root / 'cheat.7z'), '.'], cwd=src,
                   check=True, capture_output=True)
    monkeypatch.setattr(player_install, 'host', lambda: 'linux')
    monkeypatch.setattr(player_install, '_seven_zip', lambda h, work: Path('/usr/bin/7zz'))
    assert cheats.import_folder(root)['copied']['mame'] == 1
    assert cheats.mame_names('pacman.zip') == ['Infinite Lives', 'Invincibility']
