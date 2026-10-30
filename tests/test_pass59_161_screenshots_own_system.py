"""PASS-59-161: IGDB and RAWG attach screenshots to a game, not to one
platform's version, so they count only when the game is on one platform."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper import metadata_merger as mod
from scraper import scrape_igdb, scrape_rawg

ONE = [{'id': 26, 'name': 'ZX Spectrum'}]
SEVERAL = ONE + [{'id': 15, 'name': 'Commodore C64/128/MAX'}]
IGDB_SHOTS = [{'url': '//img/t_thumb/a.jpg'}]
RAWG_SHOTS = ['https://img/a.jpg']


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    """Point the merger at a scratch folder and record each download."""
    os.makedirs(tmp_path / 'screenshots')
    monkeypatch.setattr(mod, 'IMAGE_PATH', str(tmp_path))
    urls = []

    def fake_download(url, local_path, *args, **kwargs):
        urls.append(url)
        return True

    monkeypatch.setattr(mod, '_download_and_finalize', fake_download)
    monkeypatch.setattr(mod, 'keep_screenshot_if_unique', lambda *a, **kw: True)
    return urls


def _metadata():
    return {key: None for key in (
        'title', 'publisher', 'developer', 'release_date', 'genre', 'description',
        'modes', 'players', 'boxart', 'screenshots', 'fanart', 'franchise',
        'esrb_rating', 'alternate_titles')}


@pytest.mark.parametrize('platforms, kept', [(ONE, True), (SEVERAL, False), (None, False)])
def test_igdb_screenshots_need_one_platform(downloads, platforms, kept):
    metadata = _metadata()
    data = {'screenshots': IGDB_SHOTS}
    if platforms is not None:
        data['platforms'] = platforms
    mod.apply_igdb_to_metadata(metadata, data, 1, {'filled_fields': []})
    assert bool(downloads) is kept
    assert bool(metadata['screenshots']) is kept


@pytest.mark.parametrize('platforms, kept', [(ONE, True), (SEVERAL, False), (None, False)])
def test_rawg_screenshots_need_one_platform(downloads, platforms, kept):
    metadata = _metadata()
    data = {'screenshot_urls': RAWG_SHOTS}
    if platforms is not None:
        data['platforms'] = platforms
    mod.apply_rawg_to_metadata(metadata, data, 1, {'filled_fields': []})
    assert bool(downloads) is kept
    assert bool(metadata['screenshots']) is kept


def test_rawg_details_report_the_platforms(monkeypatch):
    def fake_request(endpoint, params=None):
        if endpoint == 'games/7':
            return {'id': 7, 'name': 'Game', 'platforms': [{'platform': {'id': 1}}]}
        return None

    monkeypatch.setattr(scrape_rawg, '_make_request', fake_request)
    assert len(scrape_rawg.get_game_details(7)['platforms']) == 1


def test_igdb_direct_details_ask_for_the_platforms(monkeypatch):
    bodies = []
    monkeypatch.setattr(scrape_igdb, 'igdb_auth', lambda: 'token')
    monkeypatch.setattr(scrape_igdb, 'igdb_request',
                        lambda endpoint, body, token: bodies.append(body) or [])
    scrape_igdb.fetch_game_details(7)
    assert 'platforms.name' in bodies[0]
