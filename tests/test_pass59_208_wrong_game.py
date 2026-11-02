"""PASS-59-208: scraping stops accepting the wrong game. Sequels, mods and other
consoles' versions no longer pass for the game being scraped, and RAWG no longer
hands one version's credits and player counts to another."""
import pytest

from scraper import metadata_merger, scrape_igdb, scrape_rawg
from scraper.hybrid_scraper import _fetch_screenscraper, _pick_best_fallback
from scraper.match_scorer import (
    calculate_rawg_score, calculate_ss_score, calculate_title_match_score,
    sequel_numbers_agree,
)
from scraper.scraper_manager import passes_match_filter

SCORE_MODE = {'mode': 'score', 'min_score': 200}


@pytest.mark.parametrize('wanted, offered', [
    ('Street Fighter II', 'Street Fighter'),
    ('Gran Turismo 3', 'Gran Turismo'),
    ('Sonic the Hedgehog', 'Sonic the Hedgehog 2'),
    ('Final Fantasy', 'Final Fantasy VII'),
    ('Doom', 'Doom II'),
    ('Mario Kart', 'Mario Kart 64'),
])
def test_a_sequel_is_not_the_game(wanted, offered):
    assert _pick_best_fallback([{'name': offered}], wanted) is None


@pytest.mark.parametrize('wanted, offered', [
    ('Doom II', 'Doom 2'),
    ('Doom II', 'Doom II Deluxe'),
    ('Sonic the Hedgehog', 'Sonic the Hedgehog 1'),
    ('Mega Man X', 'Mega Man X Collection'),
])
def test_the_same_number_written_another_way_still_matches(wanted, offered):
    assert _pick_best_fallback([{'name': offered}], wanted) is not None


def test_a_number_dropped_from_a_subtitle_is_the_same_game():
    for a, b in (('Golden Sun: The Lost Age', 'Golden Sun 2 - The Lost Age'),
                 ('Rayman: Revolution', 'Rayman 2 - Revolution'),
                 ('Crash Bandicoot 3: Warped', 'Crash Bandicoot Warped')):
        assert sequel_numbers_agree(a, b), (a, b)
    assert sequel_numbers_agree('FIFA 07', 'FIFA 7')
    assert not sequel_numbers_agree('Tiger Woods PGA Tour 2000', 'Tiger Woods PGA Tour 2004')
    assert not sequel_numbers_agree('Street Fighter II Turbo', 'Street Fighter')


@pytest.mark.parametrize('a, b', [
    ('Pokémon: Blue Version', 'Pokemon - Blue Version (USA, Europe)'),
    ("Tom Clancy's Rainbow Six", 'Tom Clancys Rainbow Six'),
    ("Conker's Pocket Tales", 'Conkers Pocket Tales'),
    ('R.B.I. Baseball 4', 'RBI Baseball 4'),
    ('Buzz! Master Quiz', 'Buzz Master Quiz'),
])
def test_accents_and_apostrophes_do_not_lower_a_match(a, b):
    assert calculate_title_match_score(a, b) >= 300


def test_a_character_python_calls_a_digit_does_not_crash_the_scorer():
    assert calculate_title_match_score('Game² Deluxe', 'Game²') > 0


def test_fallback_refuses_a_result_for_another_console():
    results = [{'name': 'Castlevania', 'platform_match': False},
               {'name': 'Castlevania Bloodlines', 'platform_match': True}]
    assert _pick_best_fallback(results, 'Castlevania')['name'] == 'Castlevania Bloodlines'
    assert _pick_best_fallback(results[:1], 'Castlevania') is None


def test_bulk_needs_a_title_match_however_many_other_points():
    assert not passes_match_filter({'score': 245, 'title_score': 0}, SCORE_MODE)
    assert not passes_match_filter({'score': 245, 'title_score': 79}, SCORE_MODE)
    assert passes_match_filter({'score': 245, 'title_score': 80}, SCORE_MODE)
    assert not passes_match_filter({'score': 199, 'title_score': 300}, SCORE_MODE)


def test_rawg_earns_nothing_for_a_picture_or_a_metacritic_score():
    plain = {'name': 'Doom', 'platform_match': True, 'release_date': '1993'}
    extras = dict(plain, image='x.jpg', metacritic=90)
    assert calculate_rawg_score(extras, 'Doom') == calculate_rawg_score(plain, 'Doom')


def test_equal_titles_are_decided_by_the_users_order_not_by_rawg_extras():
    ss = {'name': 'Doom', 'platform_match': True, 'release_date': '1993'}
    rawg = dict(ss, image='x.jpg', metacritic=90)
    assert calculate_ss_score(ss, 'Doom') >= calculate_rawg_score(rawg, 'Doom')


def _rawg_details(monkeypatch, platforms, tags):
    record = {
        'id': 7, 'name': 'Doom', 'platforms': platforms,
        'developers': [{'name': 'id Software'}],
        'publishers': [{'name': 'Activision'}],
        'genres': [{'name': 'Shooter'}],
        'esrb_rating': {'slug': 'mature'},
        'tags': [{'name': t} for t in tags],
    }
    monkeypatch.setattr(scrape_rawg, 'rate_limit', lambda *_: None)
    monkeypatch.setattr(scrape_rawg, '_make_request',
                        lambda endpoint, params=None: record if endpoint == 'games/7' else None)
    return scrape_rawg.get_game_details(7)


ONE = [{'platform': {'id': 27}}]
SEVERAL = [{'platform': {'id': 27}}, {'platform': {'id': 4}}]
TAGS = ['Singleplayer', 'Multiplayer', 'Local Co-Op', 'Online Multiplayer', 'Split Screen']


def test_a_record_for_several_consoles_gives_no_credits_or_age_rating(monkeypatch):
    data = _rawg_details(monkeypatch, SEVERAL, TAGS)
    assert data['developer'] is None
    assert data['publisher'] is None
    assert data['esrb_rating'] is None
    assert data['modes'] == 'Single-Player'
    assert data['genre'] == 'Shooter'


def test_a_record_for_one_console_keeps_them(monkeypatch):
    data = _rawg_details(monkeypatch, ONE, TAGS)
    assert data['developer'] == 'id Software'
    assert data['publisher'] == 'Activision'
    assert data['esrb_rating'] == 'M'
    assert data['modes'] == 'Single-Player, Local Co-op, Online Multiplayer, Split-Screen'


@pytest.mark.parametrize('platforms', [ONE, SEVERAL])
def test_rawg_tags_never_give_a_player_count(monkeypatch, platforms):
    assert _rawg_details(monkeypatch, platforms, ['Multiplayer', '4 Player'])['players'] is None


@pytest.mark.parametrize('folder', ['c64', 'dos'])
def test_systems_rawg_files_under_another_platform_are_not_searched(monkeypatch, folder):
    def no_request(*a, **k):
        raise AssertionError('RAWG was asked')
    monkeypatch.setattr(scrape_rawg, '_make_request', no_request)
    assert scrape_rawg.search_games('Paradroid', folder) == []


def _igdb_search(monkeypatch, games, title='Sonic the Hedgehog'):
    bodies = []
    monkeypatch.setattr(scrape_igdb, 'igdb_auth', lambda: 'token')
    monkeypatch.setattr(scrape_igdb, 'get_platform_id', lambda name: 29)
    monkeypatch.setattr(scrape_igdb, 'igdb_request',
                        lambda endpoint, body, token: bodies.append(body) or list(games))
    found = scrape_igdb.search_games(title, 'Mega Drive')
    return [g['name'] for g in found], bodies


def test_igdb_drops_a_mod_whose_title_is_not_the_roms(monkeypatch):
    names, bodies = _igdb_search(monkeypatch, [
        {'id': 1, 'name': '(Another) Shadow the Hedgehog in Sonic the Hedgehog', 'game_type': 5},
        {'id': 2, 'name': 'Sonic the Hedgehog Pack', 'game_type': 13},
        {'id': 3, 'name': 'Sonic the Hedgehog', 'game_type': 0},
    ])
    assert names == ['Sonic the Hedgehog']
    assert all('game_type' in body for body in bodies)


def test_igdb_keeps_a_hack_the_rom_is_named_after(monkeypatch):
    names, _ = _igdb_search(monkeypatch, [{'id': 1, 'name': 'Sonic Megamix', 'game_type': 5}],
                            title='Sonic Megamix')
    assert names == ['Sonic Megamix']


def _igdb_apply(multiplayer_modes, platform_id=8):
    meta = {k: None for k in ('title', 'publisher', 'developer', 'genre', 'description',
                              'modes', 'players', 'boxart', 'fanart', 'screenshots',
                              'release_date', 'release_dates')}
    meta['alternate_titles'] = []
    result = {'filled_fields': []}
    metadata_merger.apply_igdb_to_metadata(
        meta,
        {'game_modes': [{'name': 'Multiplayer'}], 'multiplayer_modes': multiplayer_modes},
        1, result, platform_id=platform_id)
    return meta


def test_igdb_player_count_comes_from_this_console():
    meta = _igdb_apply([{'platform': 6, 'offlinemax': 8, 'onlinemax': 32},
                        {'platform': 8, 'offlinemax': 2}])
    assert meta['players'] == 2
    assert meta['modes'] == 'Local Multiplayer'


def test_igdb_details_only_for_another_console_say_nothing_here():
    meta = _igdb_apply([{'platform': 6, 'offlinemax': 8, 'onlinemax': 32}])
    assert meta['players'] is None
    assert not meta['modes']


def _ss_lookup():
    return {
        'title': 'Sonic the Hedgehog', 'system_folder': 'megadrive', 'user_ticked': True,
        'secondary_sources': [{'source': 'screenscraper', 'id': '3192:1', 'name': 'Sonic'}],
        'api_keys': {'screenscraper_username': 'u', 'screenscraper_password': 'p'},
    }


def test_a_picked_screenscraper_game_is_fetched_by_id_when_the_cache_expired(monkeypatch):
    from scraper import scrape_screenscraper
    sent = {}

    class Reply:
        status_code = 200
        text = ''

        @staticmethod
        def json():
            return {'response': {'jeu': {'id': '3192', 'noms': []}}}

    def request(url, params, timeout=60):
        sent.update(dict(params))
        return Reply()

    monkeypatch.setattr(scrape_screenscraper, '_ss_request_with_retry', request)
    monkeypatch.setattr('scraper.scraper_manager.get_cached_screenscraper_result',
                        lambda *a: None)
    assert _fetch_screenscraper(_ss_lookup())['id'] == '3192'
    assert sent['gameid'] == '3192'
    assert sent['systemeid'] == '1'
    assert 'jeuid' not in sent


def test_screenscraper_rom_lookup_keeps_the_id_and_reads_the_matched_rom():
    from scraper.hybrid_scraper import source_game_id
    from scraper.scrape_screenscraper import parse_game_data
    parsed = parse_game_data({
        'id': '3192',
        'rom': {'romfilename': 'Sonic (USA).zip', 'romregions': 'us'},
        'roms': [{'romfilename': '002 Sonic 2.bin', 'regions': {}}],
    })
    assert source_game_id(parsed) == 3192
    assert parsed['rom_info'] == {'romfilename': 'Sonic (USA).zip', 'romregions': 'us'}


def test_esde_search_leaves_out_a_sequel(monkeypatch):
    from scraper import scrape_esde
    monkeypatch.setattr(scrape_esde, 'find_gamelist_xml', lambda folder: 'gamelist.xml')
    monkeypatch.setattr(scrape_esde, 'parse_gamelist_xml', lambda path: [
        {'name': 'Sonic the Hedgehog 2', 'path': './a.zip'},
        {'name': 'Sonic the Hedgehog', 'path': './b.zip'},
    ])
    found = scrape_esde.search_esde_games('Sonic the Hedgehog', 'megadrive')
    assert [g['name'] for g in found] == ['Sonic the Hedgehog']


def test_one_default_source_order_with_rawg_last():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    order = "['screenscraper', 'esde', 'tgdb', 'igdb', 'rawg'"
    assert order in (root / 'templates/game_detail.html').read_text(encoding='utf-8')
    assert order in (root / 'templates/settings.html').read_text(encoding='utf-8')
    for path in ('app.py', 'routes/settings.py', 'routes/bulk_scrape.py', 'scraper/hybrid_scraper.py'):
        text = (root / path).read_text(encoding='utf-8')
        assert 'DEFAULT_SCRAPER_PRIORITY' in text, path
