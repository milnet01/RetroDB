"""PASS-59-155 INV-7 to INV-9 — the cheat store: pack downloads and folder
imports. docs/specs/PASS-59-155-cheats.md §4.1–4.3.

No network: each download serves a zip built in tmp_path through a stub of
requests.get.
"""
import hashlib
import zipfile

import pytest

from services import cheats

RA_CHT = 'cheats = 1\n\ncheat0_desc = "Infinite Lives"\ncheat0_code = "7E0DBE09"\ncheat0_enable = false\n'
DS_CHT = '[Infinite Health]\nType = Gameshark\nActivation = EndFrame\n800BF5AC 00CF\n'
PNACH = 'gametitle=Some Game [SLUS-20001] [67454C1E]\n\n[Infinite Credits]\npatch=1,EE,01FA9BF0,extended,00000009\n'


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path / 'base'))
    return cheats.store_dir()


def _serve(monkeypatch, tmp_path, members):
    """Make the next download return a zip of {member name: text}."""
    zpath = tmp_path / 'served.zip'
    with zipfile.ZipFile(zpath, 'w') as zf:
        for name, text in members.items():
            zf.writestr(name, text)

    class Resp:
        status_code = 200
        url = 'https://codeload.github.com/served.zip'

        def iter_content(self, size):
            yield zpath.read_bytes()

        def close(self):
            pass
    monkeypatch.setattr('services.cheats.requests.get', lambda url, stream=False, timeout=None: Resp())


def _tree_hash(root):
    h = hashlib.sha256()
    for p in sorted(root.rglob('*')):
        h.update(str(p.relative_to(root)).encode())
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()


def test_download_unpacks_each_pack_layout(store, tmp_path, monkeypatch):
    _serve(monkeypatch, tmp_path, {'Sony - PlayStation/Crash (USA).cht': RA_CHT,
                                   'Sony - PlayStation/readme.txt': 'x'})
    assert cheats.download_pack('retroarch') == 1
    assert (store / 'packs/retroarch/Sony - PlayStation/Crash (USA).cht').read_text() == RA_CHT
    _serve(monkeypatch, tmp_path, {'repo-main/cheats/67454C1E.pnach': PNACH,
                                   'repo-main/README.md': 'x'})
    assert cheats.download_pack('pcsx2') == 1
    assert (store / 'packs/pcsx2/67454C1E.pnach').is_file()
    assert cheats.pack_sources()['pcsx2']['files'] == 1


# INV-7 ------------------------------------------------------------------------

@pytest.mark.parametrize('bad', ['../x.cht', '/abs/x.cht', 'Sony - PlayStation/../../x.cht'])
def test_inv7_unsafe_member_fails_and_old_pack_stays(store, tmp_path, monkeypatch, bad):
    _serve(monkeypatch, tmp_path, {'Sony - PlayStation/Old (USA).cht': RA_CHT})
    cheats.download_pack('retroarch')
    before = _tree_hash(store / 'packs')
    _serve(monkeypatch, tmp_path, {'Sony - PlayStation/New (USA).cht': RA_CHT, bad: RA_CHT})
    with pytest.raises(cheats.CheatError):
        cheats.download_pack('retroarch')
    assert _tree_hash(store / 'packs') == before
    assert not (store.parent / 'x.cht').exists() and not (store / 'x.cht').exists()


def test_inv7_not_a_zip_fails_and_old_pack_stays(store, tmp_path, monkeypatch):
    _serve(monkeypatch, tmp_path, {'SLUS-20001.cht': DS_CHT})
    cheats.download_pack('duckstation')
    (tmp_path / 'served.zip').write_bytes(b'<html>moved</html>')
    with pytest.raises(cheats.CheatError):
        cheats.download_pack('duckstation')
    assert (store / 'packs/duckstation/SLUS-20001.cht').read_text() == DS_CHT


# INV-8 ------------------------------------------------------------------------

def test_inv8_download_never_touches_own(store, tmp_path, monkeypatch):
    own = store / 'own' / 'retroarch' / 'Sony - PlayStation'
    own.mkdir(parents=True)
    (own / 'Crash (USA).cht').write_text('cheats = 1\n')
    before = _tree_hash(store / 'own')
    _serve(monkeypatch, tmp_path, {'Sony - PlayStation/Crash (USA).cht': RA_CHT})
    cheats.download_pack('retroarch')
    cheats.download_pack('retroarch')
    assert _tree_hash(store / 'own') == before


def test_inv8_import_never_touches_the_source(store, tmp_path):
    src = tmp_path / 'mine'
    (src / 'Snes9x').mkdir(parents=True)
    (src / 'Snes9x' / 'Mario (USA).cht').write_text(RA_CHT)
    (src / 'SLUS-00433.cht').write_text(DS_CHT)
    before = _tree_hash(src)
    cheats.import_folder(str(src))
    cheats.import_folder(str(src))
    assert _tree_hash(src) == before


# INV-9 ------------------------------------------------------------------------

def test_inv9_import_sorts_by_content(store, tmp_path):
    src = tmp_path / 'mine'
    (src / 'Snes9x').mkdir(parents=True)
    (src / 'Snes9x' / 'Mario (USA).cht').write_text(RA_CHT)
    (src / 'Sony - PlayStation').mkdir()
    (src / 'Sony - PlayStation' / 'Crash (USA).cht').write_text(RA_CHT)
    (src / 'odd').mkdir()
    (src / 'odd' / 'SLUS-00433.cht').write_text(DS_CHT)
    (src / 'odd' / 'Some Game.pnach').write_text(PNACH)
    (src / 'odd' / 'notes.txt').write_text('x')
    (src / 'odd' / 'Random (USA).cht').write_text(RA_CHT)    # no system folder
    result = cheats.import_folder(str(src))
    own = store / 'own'
    assert (own / 'retroarch/Nintendo - Super Nintendo Entertainment System/Mario (USA).cht').is_file()
    assert (own / 'retroarch/Sony - PlayStation/Crash (USA).cht').is_file()
    assert (own / 'duckstation/SLUS-00433.cht').read_text() == DS_CHT
    assert (own / 'pcsx2/SLUS-20001_67454C1E.pnach').read_text() == PNACH
    assert result['copied'] == {'retroarch': 2, 'duckstation': 1, 'pcsx2': 1}
    assert sorted(s['file'] for s in result['skipped']) == sorted(
        [str(src / 'odd' / 'notes.txt'), str(src / 'odd' / 'Random (USA).cht')])


def test_import_again_changes_nothing_then_replaces_a_changed_file(store, tmp_path):
    src = tmp_path / 'mine'
    src.mkdir()
    (src / 'SLUS-00433.cht').write_text(DS_CHT)
    cheats.import_folder(str(src))
    assert cheats.import_folder(str(src))['unchanged'] == 1
    (src / 'SLUS-00433.cht').write_text(DS_CHT + '\n[More]\nType = Gameshark\n')
    assert cheats.import_folder(str(src))['copied']['duckstation'] == 1
    assert '[More]' in (store / 'own/duckstation/SLUS-00433.cht').read_text()


def test_import_refuses_a_missing_folder(store, tmp_path):
    with pytest.raises(cheats.CheatError):
        cheats.import_folder(str(tmp_path / 'nope'))


def test_a_download_redirected_to_another_host_fails(store, tmp_path, monkeypatch):
    class Moved:
        status_code = 200
        url = 'https://elsewhere.example/x.zip'

        def close(self):
            pass
    monkeypatch.setattr('services.cheats.requests.get',
                        lambda url, stream=False, timeout=None: Moved())
    with pytest.raises(cheats.CheatError):
        cheats.download_pack('duckstation')
    assert not (store / 'packs' / 'duckstation').exists()
