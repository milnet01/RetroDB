"""PASS-59-216: data the sources already send, and RetroDB used to drop."""
import collections
from types import SimpleNamespace

import pytest

from scraper import hybrid_scraper, metadata_merger, scrape_ai, scrape_screenscraper, scrape_thegamesdb
from tests.test_pass59_161_screenshots_own_system import downloads  # noqa: F401  (a fixture)
from tests.test_pass59_205_esde_merge import library  # noqa: F401  (a fixture)
from tests.test_pass59_209_hltb import _game, db  # noqa: F401  (db is a fixture)


def _metadata(**stored):
    return collections.defaultdict(lambda: None, stored)


def _result():
    return {'filled_fields': []}


# --- ES-DE's rating ---------------------------------------------------------

@pytest.mark.parametrize('rating, score', [
    ('0.5', 50.0), ('1', 100.0), (0.85, 85.0),
    ('0', None), ('', None), (None, None), ('five', None), ('7', None),
])
def test_esde_rating_score(rating, score):
    assert hybrid_scraper.esde_rating_score(rating) == score


def test_an_online_score_beats_the_esde_rating():
    metadata = _metadata(user_score=71.0, _esde_rating=50.0)
    hybrid_scraper._use_esde_rating(metadata, _result())
    assert metadata['user_score'] == 71.0
    assert '_esde_rating' not in metadata


def test_the_esde_rating_fills_an_empty_score():
    metadata, result = _metadata(_esde_rating=50.0), _result()
    hybrid_scraper._use_esde_rating(metadata, result)
    assert metadata['user_score'] == 50.0
    assert 'user_score (ES-DE)' in result['filled_fields']


def test_a_scrape_saves_the_esde_rating(library, monkeypatch):  # noqa: F811
    library.add_game()
    monkeypatch.setattr('scraper.scrape_esde.fetch_esde_game_details',
                        lambda *a, **k: {'name': 'Fatal Run', 'rating': '0.5'})
    hybrid_scraper.apply_hybrid_metadata(1, 'esde', 'Fatal Run', 'atari2600', fill_gaps=False)
    assert library.row()['user_score'] == 50.0


# --- Other titles -----------------------------------------------------------

def test_igdb_regional_titles_become_other_titles():
    metadata = _metadata(title='Gran Turismo 3: A-Spec')
    answer = {'game_localizations': [
        {'name': 'グランツーリスモ 3: A-spec', 'region': {'id': 3, 'name': 'Japan', 'identifier': 'ja-JP'}},
        {'id': 48892, 'region': {'id': 4, 'name': 'Europe', 'identifier': 'EU'}},  # as sent: no name
        9,
    ]}
    metadata_merger.apply_igdb_to_metadata(metadata, answer, 1, _result())
    titles = metadata['alternate_titles']
    assert [t['title'] for t in titles] == ['グランツーリスモ 3: A-spec']
    assert titles[0]['region'] == 'JP'


def test_tgdb_alternates_become_other_titles(downloads):  # noqa: F811
    metadata, result = _metadata(), _result()
    metadata_merger.apply_tgdb_to_metadata(
        metadata, {'name': 'Out Run', 'alternates': ['OutRun', 'Out Run', '']}, 1, result)
    assert [t['title'] for t in metadata['alternate_titles']] == ['OutRun']
    assert 'alternate_titles +1 (TGDB)' in result['filled_fields']


def test_tgdb_asks_for_alternates_and_passes_them_on(monkeypatch):
    sent = {}

    def request(url, params=None, timeout=None):
        sent.update(params or {})
        return SimpleNamespace(status_code=200, json=lambda: {'code': 200, 'data': {'games': [
            {'game_title': 'Out Run', 'alternates': ['OutRun']}]}, 'include': {}})

    monkeypatch.setattr(scrape_thegamesdb, '_tgdb_request', request)
    monkeypatch.setattr(scrape_thegamesdb, '_fetch_game_images', lambda game_id: ([], [], []))
    found = scrape_thegamesdb.fetch_game_details(7)
    assert 'alternates' in sent['fields'].split(',')
    assert found['alternates'] == ['OutRun']


# --- Title screens ----------------------------------------------------------

def test_tgdb_title_screen_and_logo_ride_one_request(monkeypatch):
    images = [{'type': 'screenshot', 'filename': f's{n}.jpg'} for n in range(6)]
    images += [{'type': 'titlescreen', 'filename': 't.jpg'}, {'type': 'fanart', 'filename': 'f.jpg'},
               {'type': 'clearlogo', 'side': None, 'filename': 'clearlogo/7.png'}]
    reply = {'data': {'base_url': {'original': 'http://x/'}, 'images': {'7': images}}}
    calls = []

    def request(url, params=None, timeout=None):
        calls.append(params)
        return SimpleNamespace(status_code=200, json=lambda: reply)

    monkeypatch.setattr(scrape_thegamesdb, '_tgdb_request', request)
    shots, fanart, logos = scrape_thegamesdb._fetch_game_images(7)
    assert len(calls) == 1  # PASS-59-224 INV-4: logos ride the same request
    assert {'titlescreen', 'clearlogo'} <= set(calls[0]['filter[type]'].split(','))
    assert 'http://x/t.jpg' in shots[:5]
    assert fanart == ['http://x/f.jpg']
    assert logos == ['http://x/clearlogo/7.png']


def _ss_urls(monkeypatch, tmp_path, answer):
    urls = []
    monkeypatch.setattr(metadata_merger, 'IMAGE_PATH', str(tmp_path))

    def fake(url, path, **kwargs):
        urls.append(url)
        return True

    monkeypatch.setattr(metadata_merger, 'download_ss_media', fake)
    monkeypatch.setattr(metadata_merger, 'keep_screenshot_if_unique', lambda *a, **k: True)
    metadata_merger.apply_screenscraper_to_metadata(_metadata(), answer, 1, _result())
    return urls


def test_screenscraper_title_screen_is_among_the_shots(monkeypatch, tmp_path):
    medias = [{'type': 'ss', 'url': f'http://x/s{n}.png', 'region': 'wor'} for n in range(6)]
    medias.append({'type': 'sstitle', 'url': 'http://x/title.png', 'region': 'wor'})
    urls = _ss_urls(monkeypatch, tmp_path, {'medias': medias})
    assert 'http://x/title.png' in urls
    assert len(urls) == 5


def test_screenscraper_game_with_no_title_screen_is_unchanged(monkeypatch, tmp_path):
    medias = [{'type': 'ss', 'url': 'http://x/s.png', 'region': 'wor'}]
    assert _ss_urls(monkeypatch, tmp_path, {'medias': medias}) == ['http://x/s.png']


def test_a_rom_lookup_keeps_each_regions_date():
    jeu = {'dates': [{'region': 'jp', 'text': '1993-01-02'}, {'region': 'us', 'text': '1994-03-04'}]}
    parsed = scrape_screenscraper.parse_game_data(jeu, 'us')
    metadata = _metadata()
    metadata_merger.apply_screenscraper_to_metadata(metadata, parsed, 1, _result())
    assert metadata['release_date'] == '1994-03-04'
    assert '1993-01-02' in str(metadata['release_dates'])


# --- Other consoles ---------------------------------------------------------

def _igdb_platforms(*names):
    return [{'id': n, 'name': name} for n, name in enumerate(names, start=100)]


def test_igdb_platforms_fill_other_platforms_without_this_console():
    metadata, result = _metadata(), _result()
    answer = {'platforms': _igdb_platforms('Sega Mega Drive/Genesis', 'PC (Microsoft Windows)',
                                           'Xbox Series X|S', 'Web browser')}
    metadata_merger.apply_igdb_to_metadata(metadata, answer, 1, result, platform_id=100)
    assert metadata['other_platforms'] == 'PC, Xbox Series X'
    assert 'other_platforms (IGDB)' in result['filled_fields']


def test_one_platform_is_not_called_exclusive():
    metadata = _metadata()
    metadata_merger.apply_igdb_to_metadata(metadata, {'platforms': _igdb_platforms('SNES')}, 1,
                                           _result(), platform_id=100)
    assert not metadata['other_platforms']


def test_stored_other_platforms_stay():
    metadata = _metadata(other_platforms='Exclusive')
    metadata_merger.apply_igdb_to_metadata(
        metadata, {'platforms': _igdb_platforms('SNES', 'PlayStation')}, 1, _result(), platform_id=100)
    assert metadata['other_platforms'] == 'Exclusive'


def test_without_knowing_this_console_nothing_is_filled():
    metadata = _metadata()
    metadata_merger.apply_igdb_to_metadata(metadata, {'platforms': _igdb_platforms('SNES')}, 1, _result())
    assert not metadata['other_platforms']


def test_known_platforms_spells_each_once_and_sorted():
    assert scrape_ai.known_platforms(['Family Computer', 'NES', 'amiga', None, 'Zeebo']) == 'Amiga, NES'


# --- RetroAchievements: how rare ---------------------------------------------

@pytest.mark.parametrize('awarded, players, percent', [
    (57421, 63673, 90.2), ('10', '40', 25.0), (5, 0, None), (None, 10, None), (5, None, None),
])
def test_earned_percent(awarded, players, percent):
    from scraper.retroachievements import _earned_percent
    assert _earned_percent(awarded, players) == percent


# --- HowLongToBeat: its ID, and how many players timed it ---------------------

def _hltb_row(db, game_id):  # noqa: F811
    return db.execute("SELECT hltb_id, hltb_players FROM games WHERE id = ?", (game_id,)).fetchone()


def test_a_saved_match_keeps_its_id_and_player_count(db):  # noqa: F811
    from services.hltb_service import lookup_service as lookup
    game_id = _game(db, 'Tetris')
    lookup.save_result(game_id, {'playtime': 'Main: 2 hrs', 'hltb_id': '42', 'players': 613})
    assert tuple(_hltb_row(db, game_id)) == (42, 613)
    lookup.clear(game_id)
    assert tuple(_hltb_row(db, game_id)) == (None, None)


def test_a_saved_match_refuses_an_id_that_is_not_a_number(db):  # noqa: F811
    from services.hltb_service import lookup_service as lookup
    game_id = _game(db, 'Tetris')
    lookup.save_result(game_id, {'playtime': 'Main: 2 hrs', 'hltb_id': '"><script>'})
    assert _hltb_row(db, game_id)['hltb_id'] is None


def test_approving_a_queued_match_carries_them(db):  # noqa: F811
    from services.hltb_service import pending_queue
    game_id = _game(db, 'Tetris')
    db.execute("INSERT INTO hltb_pending_matches (game_id, hltb_id, players, match_name, playtime, reason) "
               "VALUES (?, 42, 613, 'Tetris', 'Main: 2 hrs', 'low_confidence')", (game_id,))
    db.commit()
    pending_queue.approve(db.execute("SELECT id FROM hltb_pending_matches").fetchone()['id'])
    assert tuple(_hltb_row(db, game_id)) == (42, 613)


def test_approving_a_stored_match_does_not_lose_them(db):  # noqa: F811
    from services.hltb_service import pending_queue
    game_id = _game(db, 'Spider-Man 2', platform='PC')
    db.execute("UPDATE games SET hltb_id = 42, hltb_players = 613 WHERE id = ?", (game_id,))
    db.commit()
    pending_queue.queue_stored_suspects()
    pending_queue.approve_all('stored')
    assert tuple(_hltb_row(db, game_id)) == (42, 613)


def test_lookup_reports_how_many_players_timed_it():
    from unittest.mock import patch

    from scraper import hltb_lookup
    hit = {'game_id': 42, 'game_name': 'Contra', 'comp_main': 36000, 'comp_plus': 0, 'comp_100': 0,
           'profile_platform': 'PC', 'release_world': 1988, 'comp_all_count': 613}
    with patch.object(hltb_lookup, '_search_hltb', return_value=[hit]):
        assert hltb_lookup.lookup_playtime('Contra', 'pc')['players'] == 613
