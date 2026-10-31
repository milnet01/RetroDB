"""Each scraper searches the right console (PASS-59-201).

Numbers checked 2026-10-31 against each service's public list: TheGamesDB's
platform page, RetroAchievements' rc_consoles.h, and for the rest the lists
Skyscraper (ScreenScraper) and RomM (IGDB, HowLongToBeat) publish.
"""
import ast
import pathlib

import pytest

import config
from scraper import hltb_lookup, retroachievements, scrape_igdb, scrape_screenscraper, scrape_thegamesdb

ROOT = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('name, expected', [
    ('Atari Lynx', '4924'),              # was Jaguar CD
    ('atarilynx', '4924'),
    ('PC Engine SuperGrafx', None),      # was Game & Watch; TGDB lists none
    ('Cps1', '23'),                      # "ps1" inside "cps1" gave PlayStation
    ('Cps3', '23'),
    ('Super Famicom', '6'),              # "famicom" gave NES
    ('Famicom Disk System', '4936'),
    ('Snesna', '6'),                     # "nes" inside "snesna" gave NES
    ('Atari Jaguar CD', '29'),
    ('Commodore Amiga CD32', '4947'),
    ('Bandai WonderSwan Color', '4926'),
    ('Philips CD-i', '4917'),
    ('Microsoft Windows', '1'),
    ('Nowhere Nes Machine', None),       # part of a name is not a match
    ('sony Nowhere', None),
])
def test_tgdb_system(name, expected):
    got = scrape_thegamesdb.get_system_id(name)
    assert (None if got is None else str(got)) == expected


@pytest.mark.parametrize('name, expected', [
    ('PC Engine SuperGrafx', 128),       # "nes" inside it gave NES
    ('Cps2', 52),                        # was PlayStation 2
    ('Cps3', 52),
    ('Snesna', 19),
    ('Super Famicom', 58),
    ('Bandai WonderSwan Color', 123),
    ('Atari Jaguar CD', 410),
    ('Commodore Amiga CD32', 114),
    ('PC Engine CD', 150),
    ('Nintendo 64DD', 416),
    ('Apple IIGS', 115),
    ('Super Game Boy', None),            # was Game Boy; IGDB lists none
    ('ZX Spectrum Next', None),          # was ZX Spectrum
    ('MSX Turbo R', None),               # was MSX
    ('Philips CD-i', 117),
    ('Sega Mega Drive', 29),
    ('megadrive', 29),
    ('Nowhere Nes Machine', None),
])
def test_igdb_platform(name, expected):
    assert scrape_igdb.get_platform_id(name) == expected


@pytest.mark.parametrize('lookup', [
    scrape_thegamesdb.get_system_id, scrape_igdb.get_platform_id,
], ids=['tgdb', 'igdb'])
def test_folder_and_display_name_agree(lookup):
    """The scrapers are handed a system's name, other callers its folder."""
    differ = {folder: (lookup(folder), lookup(name))
              for folder, name in config.SYSTEM_NAME_MAP.items()
              if lookup(folder) != lookup(name)}
    assert not differ


@pytest.mark.parametrize('module, name', [
    ('scrape_thegamesdb', 'TGDB_SYSTEM_MAP'), ('scrape_igdb', 'IGDB_PLATFORM_MAP'),
])
def test_maps_reach_existing_installs(module, name):
    """An update never rewrites config.py, so a map kept there stays wrong."""
    tree = ast.parse((ROOT / 'scraper' / f'{module}.py').read_text(encoding='utf-8'))
    from_config = {alias.name for node in ast.walk(tree)
                   if isinstance(node, ast.ImportFrom) and node.module == 'config'
                   for alias in node.names}
    assert name not in from_config
    example = ast.parse((ROOT / 'config.example.py').read_text(encoding='utf-8'))
    assigned = {t.id for node in example.body if isinstance(node, ast.Assign)
                for t in node.targets if isinstance(t, ast.Name)}
    assert name not in assigned


def _fake_tgdb(monkeypatch, games_by_platform):
    """Answers as the live service does: one platform filter, one list."""
    sent = []

    def fake(url, params=None, timeout=None):
        platform = params['filter[platform]']
        sent.append(platform)
        games = [{'id': 1, 'game_title': 'Sonic', 'platform': int(platform)}
                 ] if platform in games_by_platform else []

        class Reply:
            status_code = 200

            @staticmethod
            def json():
                return {'code': 200, 'data': {'games': games}}

        return Reply()

    monkeypatch.setattr(scrape_thegamesdb, '_tgdb_request', fake)
    return sent


@pytest.mark.parametrize('system, first', [
    ('Sega Mega Drive', '36'), ('megadrivejp', '36'), ('Sega Genesis', '18'),
])
def test_tgdb_own_list_found_asks_once(monkeypatch, system, first):
    """Each request spends the monthly allowance."""
    sent = _fake_tgdb(monkeypatch, {'18', '36'})
    results = scrape_thegamesdb.search_games('Sonic', system)
    assert sent == [first]
    assert results[0]['platform_match'] is True


def test_tgdb_mega_drive_falls_back_to_genesis_list(monkeypatch):
    """TheGamesDB files the one console under two platforms."""
    sent = _fake_tgdb(monkeypatch, {'18'})
    results = scrape_thegamesdb.search_games('Sonic', 'Sega Mega Drive')
    assert sent == ['36', '18']
    assert results[0]['platform_match'] is True


def test_tgdb_never_sends_a_platform_list(monkeypatch):
    """A comma-separated filter is ignored by the live service, which then
    returns every platform (tried 2026-10-31), though its API documents one."""
    sent = _fake_tgdb(monkeypatch, set())
    for name in scrape_thegamesdb.TGDB_SYSTEM_MAP:
        sent.clear()
        scrape_thegamesdb.search_games('Sonic', name)
        assert sent and all(',' not in p for p in sent), name


@pytest.mark.parametrize('folder, console', [
    ('wii', 19), ('pc98', 48),            # were DSi and PC-FX
    ('neogeocd', 56), ('neogeocdjp', 56), ('fds', 81), ('pcfx', 49),
    ('channelf', 57), ('odyssey2', 23), ('videopac', 23), ('atarijaguarcd', 77),
    ('megaduck', 69), ('supervision', 63), ('wasm4', 72), ('arduboy', 71),
    ('sfc', 3), ('snesna', 3), ('famicom', 7), ('megacd', 9), ('megacdjp', 9),
    ('megadrivejp', 1), ('saturnjp', 39), ('sega32xjp', 10), ('sega32xna', 10),
    ('mark3', 11), ('tg-cd', 76), ('supergrafx', 8), ('msx1', 29), ('msx2', 29),
])
def test_ra_console(folder, console):
    assert retroachievements.get_ra_console_id(folder) == console


def test_ra_has_no_neo_geo_entry():
    """Its number was the Neo Geo Pocket's, which gave Pocket achievements."""
    assert retroachievements.get_ra_console_id('neogeo') is None
    assert retroachievements.get_ra_console_id('ngp') == 14


@pytest.mark.parametrize('folder, platform', [
    ('intellivision', 'Intellivision'), ('cdimono1', 'Philips CD-i'),
    ('colecovision', 'ColecoVision'), ('atari800', 'Atari 8-bit Family'),
    ('sfc', 'Super Nintendo'), ('megacd', 'Sega CD'), ('megacdjp', 'Sega CD'),
    ('megadrivejp', 'Sega Mega Drive/Genesis'), ('saturnjp', 'Sega Saturn'),
    ('tg-cd', 'TurboGrafx-CD'), ('mark3', 'Sega Master System'),
    ('pcfx', 'NEC PC-FX'), ('vectrex', 'Vectrex'),
    ('wonderswan', 'WonderSwan'), ('wonderswancolor', 'WonderSwan'),
])
def test_hltb_platform(folder, platform):
    assert hltb_lookup.SYSTEM_TO_HLTB_PLATFORM[folder] == platform


@pytest.mark.parametrize('folder, system', [
    ('megacd', 20), ('megacdjp', 20), ('ngage', 30), ('x1', 220),
    ('neogeocdjp', 70), ('naomigd', 56), ('snesna', 4), ('mark3', 2),
    ('videopac', 104), ('amiga600', 64), ('amiga1200', 64), ('cps', 75),
    ('amigacd32', 130), ('cdtv', 129), ('apple2', 86), ('apple2gs', 217),
    ('zx81', 77), ('ti99', 205), ('samcoupe', 213), ('oric', 131),
    ('trs-80', 144), ('macintosh', 146), ('bbcmicro', 37), ('dragon32', 91),
    ('plus4', 99), ('moto', 141), ('daphne', 49), ('supervision', 207),
    ('gamecom', 121), ('tic80', 222),
])
def test_screenscraper_system(folder, system):
    assert scrape_screenscraper.get_system_id(folder) == system
