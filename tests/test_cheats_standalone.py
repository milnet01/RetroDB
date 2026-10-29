"""PASS-59-155 INV-4 to INV-6 — DuckStation and PCSX2 cheat switches,
written into the emulator's own files. docs/specs/PASS-59-155-cheats.md §4.5.
"""
import pytest

from services import cheats
from tests.test_standalone_settings import _isolated_home, seed  # noqa: F401  (fixtures)

DS_CHT = ('[A]\nType = Gameshark\n800BF5AC 00CF\n\n[B]\nType = Gameshark\n800BF5AE 00CF\n\n'
          '[C]\nType = Gameshark\n800F4534 007F\n')
PNACH = ('gametitle=Game [SLUS-20001] [67454C1E]\npatch=1,EE,00000001,extended,00000001\n\n'
         '[A]\npatch=1,EE,00000002,extended,00000001\n\n[B]\npatch=1,EE,00000003,extended,00000001\n\n'
         '[C]\npatch=1,EE,00000004,extended,00000001\n')
OTHER_LINES = ['[Patches]\n', 'Enable = Widescreen 16:9\n', '\n', '[GPU]\n', 'ResolutionScale = 4\n']


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path / 'base'))
    return cheats.store_dir()


def _setup(seed, store, kind):  # noqa: F811
    row = seed(kind=kind)
    if kind == 'duckstation-qt':
        (store / 'own/duckstation').mkdir(parents=True)
        (store / 'own/duckstation/SLUS-20001.cht').write_text(DS_CHT)
        settings = row['data'] / 'gamesettings' / 'SLUS-20001.ini'
        row['emu_file'] = row['data'] / 'cheats' / 'SLUS-20001.cht'
    else:
        (store / 'packs/pcsx2').mkdir(parents=True)
        (store / 'packs/pcsx2/SLUS-20001_67454C1E.pnach').write_text(PNACH)
        settings = row['data'] / 'gamesettings' / 'SLUS-20001_67454C1E.ini'
        row['emu_file'] = row['data'] / 'cheats' / 'SLUS-20001_67454C1E.pnach'
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(''.join(OTHER_LINES))
    row['settings'] = settings
    return row


def _enabled(view):
    return [c['name'] for c in view['cheats'] if c['enabled']]


# INV-4 ------------------------------------------------------------------------

@pytest.mark.parametrize('kind', ['duckstation-qt', 'pcsx2-qt'])
def test_inv4_the_emulators_own_cheat_file_is_never_overwritten(seed, store, kind):  # noqa: F811
    row = _setup(seed, store, kind)
    theirs = DS_CHT.replace('[C]', '[Mine]') if kind == 'duckstation-qt' else PNACH.replace('[C]', '[Mine]')
    row['emu_file'].parent.mkdir(parents=True)
    row['emu_file'].write_text(theirs)
    cheats.save(row['gid'], ['A'])
    assert row['emu_file'].read_text() == theirs
    assert 'Mine' in [c['name'] for c in cheats.game_view(row['gid'])['cheats']]


@pytest.mark.parametrize('kind', ['duckstation-qt', 'pcsx2-qt'])
def test_inv4_a_missing_cheat_file_is_copied_in(seed, store, kind):  # noqa: F811
    row = _setup(seed, store, kind)
    cheats.save(row['gid'], ['A'])
    assert row['emu_file'].read_text() == (DS_CHT if kind == 'duckstation-qt' else PNACH)


# INV-5 ------------------------------------------------------------------------

@pytest.mark.parametrize('kind,flag_section', [('duckstation-qt', 'Cheats'), ('pcsx2-qt', 'EmuCore')])
def test_inv5_save_writes_exactly_the_enabled_names(seed, store, kind, flag_section):  # noqa: F811
    row = _setup(seed, store, kind)
    cheats.save(row['gid'], ['A', 'C'])
    lines = row['settings'].read_text().splitlines(keepends=True)
    assert lines[:len(OTHER_LINES)] == OTHER_LINES
    text = ''.join(lines)
    assert text.count('Enable = ') == 3      # A, C, and [Patches]' own line
    from services.standalone_settings import read_value, read_values
    assert read_values(lines, 'Cheats', 'Enable') == ['A', 'C']
    assert read_value(lines, {'section': flag_section, 'key': 'EnableCheats'}) == 'true'
    cheats.save(row['gid'], [])
    lines = row['settings'].read_text().splitlines(keepends=True)
    assert read_values(lines, 'Cheats', 'Enable') == []
    assert read_value(lines, {'section': flag_section, 'key': 'EnableCheats'}) == 'false'
    assert lines[:len(OTHER_LINES)] == OTHER_LINES


def test_inv5_enabled_names_retrodb_does_not_list_are_kept(seed, store):  # noqa: F811
    row = _setup(seed, store, 'duckstation-qt')
    row['settings'].write_text(''.join(OTHER_LINES) + '\n[Cheats]\nEnable = Built In\n')
    cheats.save(row['gid'], ['B'])
    from services.standalone_settings import read_values
    lines = row['settings'].read_text().splitlines(keepends=True)
    assert read_values(lines, 'Cheats', 'Enable') == ['B', 'Built In']


# INV-6 ------------------------------------------------------------------------

@pytest.mark.parametrize('kind,flag_section', [('duckstation-qt', 'Cheats'), ('pcsx2-qt', 'EmuCore')])
def test_inv6_the_panel_reads_the_emulators_files(seed, store, kind, flag_section):  # noqa: F811
    row = _setup(seed, store, kind)
    cheats.save(row['gid'], ['A'])
    text = row['settings'].read_text().replace('Enable = A', 'Enable = B')
    row['settings'].write_text(text)
    view = cheats.game_view(row['gid'])
    assert _enabled(view) == ['B']
    assert view['emulator'] == ('duckstation' if kind == 'duckstation-qt' else 'pcsx2')
    assert view['always_on'] is (kind == 'pcsx2-qt')


def test_no_settings_file_name_gives_the_reason(seed, store):  # noqa: F811
    row = seed(kind='duckstation-qt', serial='')
    view = cheats.game_view(row['gid'])
    assert view['cheats'] == [] and view['reason']
    with pytest.raises(cheats.CheatError):
        cheats.save(row['gid'], ['A'])
