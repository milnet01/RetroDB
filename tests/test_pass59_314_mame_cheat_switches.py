"""PASS-59-314: switches for MAME cheats on the game page.

The import notes which of a set's cheats are plain on/off ones. The page's
choices live in own/mame/on/<set>.txt; a Lua script MAME runs at start
(-autoboot_script) switches them on and writes MAME's switches back there
when the game stops. Whether MAME obeys the script is checked by hand
(spec §7): the suite cannot run MAME.
"""

import sqlite3

import pytest

from services import cheats
from tests.test_pass59_313_mame_cheats import _download_folder, fake_7zip, store  # noqa: F401

XML = """<mamecheat version="1">
  <cheat desc="Infinite Lives"><script state="run"><action>maincpu.pb@0000=03</action></script></cheat>
  <cheat desc="Fast Shoot">
    <script state="on"><action>temp0=maincpu.pb@0002</action></script>
    <script state="off"><action>maincpu.pb@0002=temp0</action></script>
  </cheat>
  <cheat desc="Select Starting Stage"><parameter min="1" max="8" step="1"/>
    <script state="run"><action>maincpu.pb@0003=param</action></script></cheat>
  <cheat desc="Finish Stage Now"><script state="on"><action>maincpu.pb@0004=01</action></script></cheat>
  <cheat desc="Notes"><comment>no script</comment></cheat>
</mamecheat>
"""
SWITCHES = ['Infinite Lives', 'Fast Shoot']
LOCKED = ['Select Starting Stage', 'Finish Stage Now', 'Notes']


@pytest.fixture
def galaga(store, fake_7zip):  # noqa: F811
    cheats.import_folder(_download_folder(store / 'download', [], extra={'galaga.xml': XML}))
    return '/roms/mame/galaga.zip'


def _view(rom):
    return {c['name']: (c['enabled'], c['locked']) for c in cheats.mame_view(rom)}


def test_only_plain_on_off_cheats_get_a_switch(galaga):
    view = _view(galaga)
    assert [n for n, (_on, locked) in view.items() if not locked] == SWITCHES
    assert [n for n, (_on, locked) in view.items() if locked] == LOCKED
    assert not any(on for on, _locked in view.values())


def test_a_save_keeps_the_switched_on_names_for_the_next_start(galaga):
    cheats.mame_save(galaga, ['Fast Shoot', 'Finish Stage Now', 'Not In The File', 'Infinite Lives'])
    on = cheats.mame_dir() / 'on' / 'galaga.txt'
    assert on.read_text(encoding='utf-8').splitlines() == SWITCHES
    assert _view(galaga)['Fast Shoot'] == (True, False)
    assert _view(galaga)['Finish Stage Now'] == (False, True)


def test_switching_all_off_removes_the_choices(galaga):
    cheats.mame_save(galaga, ['Infinite Lives'])
    cheats.mame_save(galaga, [])
    assert not (cheats.mame_dir() / 'on' / 'galaga.txt').exists()
    assert not any(on for on, _locked in _view(galaga).values())


def test_what_mame_wrote_back_shows_on_the_page(galaga):
    on = cheats.mame_dir() / 'on'
    on.mkdir()
    (on / 'galaga.txt').write_text('Fast Shoot\n', encoding='utf-8')
    assert _view(galaga)['Fast Shoot'] == (True, False)
    assert _view(galaga)['Infinite Lives'] == (False, False)


def test_a_save_needs_the_names(galaga):
    with pytest.raises(cheats.CheatError):
        cheats.mame_save(galaga, None)


def test_a_set_with_no_cheats_cannot_be_saved(galaga):
    with pytest.raises(cheats.CheatError):
        cheats.mame_save('/roms/mame/pacman.zip', ['Infinite Lives'])
    assert not (cheats.mame_dir() / 'on' / 'pacman.txt').exists()


def test_a_collection_imported_before_switches_lists_names_locked(store):  # noqa: F811
    d = cheats.mame_dir()
    d.mkdir(parents=True)
    con = sqlite3.connect(d / 'names.sqlite3')
    con.execute('CREATE TABLE cheats (game TEXT PRIMARY KEY, names TEXT NOT NULL) WITHOUT ROWID')
    con.execute("INSERT INTO cheats VALUES ('galaga', 'Infinite Lives')")
    con.commit()
    con.close()
    assert _view('galaga.zip') == {'Infinite Lives': (False, True)}


def test_the_launch_runs_the_switching_script(galaga):
    args = cheats.mame_launch_args()
    script = cheats.mame_dir() / 'retrodb.lua'
    assert args == ['-plugin', 'cheat', '-cheatpath', str(cheats.mame_dir()),
                    '-autoboot_script', str(script)]
    text = script.read_text(encoding='utf-8')
    assert 'emu.plugin.cheat' in text and 'add_machine_stop_notifier' in text
    assert (cheats.mame_dir() / 'on').is_dir()


def test_a_script_that_cannot_be_written_still_launches_with_cheats(galaga, monkeypatch):
    def refuse(*_a, **_k):
        raise OSError('read-only')
    monkeypatch.setattr(cheats, '_write_mame_script', refuse)
    assert cheats.mame_launch_args() == ['-plugin', 'cheat', '-cheatpath', str(cheats.mame_dir())]
