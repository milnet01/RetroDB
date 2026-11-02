"""PASS-59-217: games are identified from the ROM file itself
(docs/specs/PASS-59-217-identify-by-file.md §5, one test per invariant)."""
import os
import sqlite3
import zipfile
from types import SimpleNamespace

import pytest

from scraper import hybrid_scraper, scrape_screenscraper
from services import rom_identity


def _zip(path, **members):
    with zipfile.ZipFile(path, 'w') as z:
        for name, data in members.items():
            z.writestr(name.replace('__', '.'), data)
    return str(path)


# --- INV-1, INV-2, INV-11: reading the file ------------------------------------

def test_zip_identity_reads_the_directory(tmp_path, monkeypatch):
    path = _zip(tmp_path / 'Game (USA).zip', game__md=b'x' * 100, readme__txt=b'ignored' * 99)
    monkeypatch.setattr(zipfile.ZipFile, 'read', lambda *a, **k: pytest.fail('unpacked a member'))
    monkeypatch.setattr(zipfile.ZipFile, 'open', lambda *a, **k: pytest.fail('unpacked a member'))
    found = rom_identity.file_identity(path)
    assert found['name'] == 'game.md'
    assert found['size'] == 100
    assert len(found['crc']) == 8 and found['crc'] == found['crc'].upper()


def test_a_zip_of_many_files_has_no_identity(tmp_path):
    assert rom_identity.file_identity(_zip(tmp_path / 'set.zip', a__rom=b'a', b__rom=b'b')) is None


def test_a_hostile_member_name_is_only_text(tmp_path):
    path = tmp_path / 'evil.zip'
    with zipfile.ZipFile(path, 'w') as z:
        z.writestr('../../escaped.bin', b'data')
    assert rom_identity.file_identity(str(path))['name'] == '../../escaped.bin'
    assert not (tmp_path.parent / 'escaped.bin').exists()
    assert sorted(os.listdir(tmp_path)) == ['evil.zip']


def test_a_plain_file_is_read_and_a_disc_format_is_not(tmp_path):
    rom = tmp_path / 'game.gb'
    rom.write_bytes(b'abc')
    assert rom_identity.file_identity(str(rom))['crc'] == '352441C2'
    chd = tmp_path / 'game.chd'
    chd.write_bytes(b'abc')
    assert rom_identity.file_identity(str(chd)) is None


def test_a_large_plain_file_is_not_read(tmp_path, monkeypatch):
    rom = tmp_path / 'game.iso'
    rom.write_bytes(b'abc')
    monkeypatch.setattr(rom_identity, 'MAX_PLAIN_FILE', 2)
    assert rom_identity.file_identity(str(rom)) is None


@pytest.mark.parametrize('name, content', [('broken.zip', b'not a zip'), ('missing.gb', None)])
def test_a_bad_file_has_no_identity(tmp_path, name, content):
    path = tmp_path / name
    if content is not None:
        path.write_bytes(content)
    assert rom_identity.file_identity(str(path)) is None


# --- INV-3, INV-4, INV-5: asking ScreenScraper -----------------------------------

@pytest.fixture
def service(monkeypatch):
    """Records each request and answers with `replies`, in order."""
    state = SimpleNamespace(sent=[], replies=[])

    def request(url, params, timeout=60, retries=2):
        state.sent.append(dict(params))
        reply = state.replies.pop(0)
        if reply is None:
            return SimpleNamespace(status_code=404, json=lambda: {})
        return SimpleNamespace(status_code=200, json=lambda: {'response': {'jeu': reply}})

    monkeypatch.setattr(scrape_screenscraper, '_ss_request_with_retry', request)
    return state


def _identify(path, serial=None, folder='megadrive'):
    return scrape_screenscraper.identify_by_file(path, folder, serial, 'user', 'pass')


def _crc_of(path):
    return rom_identity.file_identity(path)['crc']


def test_the_exact_file_is_accepted_ignoring_case(tmp_path, service):
    path = _zip(tmp_path / 'g.zip', g__md=b'data')
    service.replies = [{'id': '7', 'rom': {'romcrc': _crc_of(path).lower()}}]
    found = _identify(path)
    assert found['id'] == '7'
    assert found['_matched_file'] is True
    assert service.sent[0]['crc'] == _crc_of(path)
    assert service.sent[0]['romnom'] == 'g.md'


def test_a_name_match_is_not_the_file(tmp_path, service):
    path = _zip(tmp_path / 'Mortal Kombat II (Japan).zip', g__gb=b'data')
    service.replies = [{'id': '3012', 'rom': {'romcrc': 'EBE53943'}}]
    assert _identify(path, folder='gb') is None


@pytest.mark.parametrize('record', [
    {'id': '1', 'notgame': 'true'},
    {'id': '1', 'notgame': True},
    {'id': '1', 'noms': [{'region': 'ss', 'text': 'ZZZ(notgame):#NONGAME'}]},
])
def test_notgame_is_refused(tmp_path, service, record):
    path = _zip(tmp_path / 'g.zip', g__md=b'data')
    service.replies = [{**record, 'rom': {'romcrc': _crc_of(path)}}]
    assert _identify(path) is None


def test_serial_lookup_cannot_match_by_name(tmp_path, service):
    disc = tmp_path / 'Real Name (USA).chd'
    disc.write_bytes(b'abc')
    service.replies = [{'id': '22415', 'rom': {}}]
    assert _identify(str(disc), serial='SLUS-20945', folder='ps2')['id'] == '22415'
    sent = service.sent[0]
    assert sent['serialnum'] == 'SLUS-20945'
    assert sent['romnom'] == 'SLUS-20945.iso'
    assert 'crc' not in sent


def test_a_file_miss_then_tries_the_serial(tmp_path, service):
    disc = tmp_path / 'small.iso'
    disc.write_bytes(b'abc')
    service.replies = [None, {'id': '5', 'rom': {}}]
    assert _identify(str(disc), serial='SLUS-20945', folder='ps2')['id'] == '5'
    assert len(service.sent) == 2


def test_no_identity_and_no_serial_sends_nothing(tmp_path, service):
    assert _identify(_zip(tmp_path / 'set.zip', a__rom=b'a', b__rom=b'b')) is None
    assert service.sent == []


def test_an_unknown_system_sends_nothing(tmp_path, service):
    assert _identify(_zip(tmp_path / 'g.zip', g__md=b'data'), folder='nosuchsystem') is None
    assert service.sent == []


# --- INV-6, INV-7: a scrape's use of it -------------------------------------------

@pytest.fixture
def scrape_calls(monkeypatch):
    calls = SimpleNamespace(file=[], search=[], by_id=[], file_answer=None)

    def file_lookup(*args):
        calls.file.append(args)
        return calls.file_answer

    monkeypatch.setattr(scrape_screenscraper, 'identify_by_file', file_lookup)
    monkeypatch.setattr(scrape_screenscraper, 'search_game',
                        lambda *a, **k: calls.search.append(a) or [])
    monkeypatch.setattr(hybrid_scraper, '_ss_record_by_id',
                        lambda ss_id, keys: calls.by_id.append(ss_id) or {'id': ss_id})
    return calls


def _lookup(**overrides):
    return {'title': 'Game', 'rom_path': '/roms/g.zip', 'system_name': 'Mega Drive',
            'system_folder': 'megadrive', 'secondary_sources': [], 'user_ticked': False,
            'disc_serial': None, 'game_id': 1,
            'api_keys': {'screenscraper_username': 'u', 'screenscraper_password': 'p'},
            **overrides}


def test_the_file_comes_first(scrape_calls):
    scrape_calls.file_answer = {'id': '7', '_matched_file': True}
    found = hybrid_scraper._fetch_screenscraper(
        _lookup(secondary_sources=[{'source': 'screenscraper', 'id': '9', 'name': 'Other'}]))
    assert found['id'] == '7'
    assert scrape_calls.search == [] and scrape_calls.by_id == []


def test_a_ticked_pick_wins(scrape_calls):
    hybrid_scraper._fetch_screenscraper(
        _lookup(user_ticked=True, secondary_sources=[{'source': 'screenscraper', 'id': '9', 'name': 'Picked'}]))
    assert scrape_calls.file == []
    assert scrape_calls.by_id == ['9']


def test_a_miss_falls_back_to_search(scrape_calls):
    hybrid_scraper._fetch_screenscraper(_lookup())
    assert scrape_calls.file
    assert scrape_calls.search


def test_a_stored_serial_is_passed_and_ps3_is_not_asked_by_serial(scrape_calls):
    hybrid_scraper._fetch_screenscraper(_lookup(system_folder='ps2', disc_serial='SLUS-20945'))
    assert 'SLUS-20945' in scrape_calls.file[0]
    scrape_calls.file.clear()
    hybrid_scraper._fetch_screenscraper(_lookup(system_folder='ps3', disc_serial='BLUS-31176'))
    assert 'BLUS-31176' not in scrape_calls.file[0]


def test_a_missing_serial_is_read_from_the_disc_for_ps1_and_ps2(scrape_calls, monkeypatch):
    read = []
    monkeypatch.setattr('services.standalone_settings.disc_ids',
                        lambda game: read.append(game) or ('SCUS-94163', None))
    hybrid_scraper._fetch_screenscraper(_lookup(system_folder='psx'))
    assert read and 'SCUS-94163' in scrape_calls.file[0]


# --- INV-8: the id ------------------------------------------------------------------

@pytest.mark.parametrize('record, stored', [
    ({'id': '77', '_matched_file': True}, 77),
    ({'id': '77'}, 5),
])
def test_file_match_replaces_the_id(record, stored):
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, igdb_id INTEGER, screenscraper_id INTEGER)")
    conn.execute("INSERT INTO games (id, screenscraper_id) VALUES (1, 5)")
    hybrid_scraper._save_source_ids(conn.cursor(), 1, {'screenscraper': record})
    assert conn.execute("SELECT screenscraper_id FROM games").fetchone()[0] == stored
    conn.close()


# --- Region and history ----------------------------------------------------------------

def test_an_exact_files_region_counts_when_the_name_has_none():
    from scraper.ss_regions import own_region
    record = {'_matched_file': True, 'rom': {'romregions': 'jp,us'}}
    assert own_region({'rom_path': '/r/Game.zip', 'region': 'USA'}, record) == 'jp'
    assert own_region({'rom_path': '/r/Game (Europe).zip'}, record) == 'Europe'
    assert own_region({'rom_path': '/r/Game.zip', 'region': 'USA'}, {'rom': {'romregions': 'jp'}}) == 'USA'


def test_the_history_says_the_file_matched(monkeypatch):
    import collections

    from scraper import metadata_merger
    result = {'filled_fields': []}
    metadata_merger.apply_screenscraper_to_metadata(
        collections.defaultdict(lambda: None), {'_matched_file': True}, 1, result)
    assert 'matched by file (ScreenScraper)' in result['filled_fields']
