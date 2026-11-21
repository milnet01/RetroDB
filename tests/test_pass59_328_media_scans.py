"""PASS-59-328: the disc or cartridge picture of ScreenScraper (support-2D) and
ES-DE (physicalmedia) kept in games.box_scans for games no source has one of,
so the open box shows it."""
import collections
import json
import os

from PIL import Image

import config
from scraper import metadata_merger
from services import box_scans
from tests.test_pass59_205_esde_merge import (  # noqa: F401  (library is a fixture)
    FATAL_RUN, _picture, _scrape, later_source, library)

SS_MEDIA = [{'type': 'support-2D', 'url': 'http://x/us.png', 'region': 'us', 'format': 'png'},
            {'type': 'support-2D', 'url': 'http://x/eu.png', 'region': 'eu', 'format': 'png'}]


def _png(path, size=(40, 70)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new('RGB', size, (200, 10, 10)).save(path, 'PNG')


def _moby(*kinds):
    return {'version': 1, 'mobygames': {'group': 1, 'items': [
        {'kind': kind, 'caption': None, 'file': f'4_{kind}_0_ab.webp', 'width': 10, 'height': 10}
        for kind in kinds]}}


def _ss(monkeypatch, tmp_path, **stored):
    """Apply a ScreenScraper record holding two support-2D pictures; returns
    the metadata and the URLs downloaded into box_scans/."""
    saved = []
    monkeypatch.setattr(metadata_merger, 'IMAGE_PATH', str(tmp_path))
    monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path))

    def download(url, path, **kwargs):
        if kwargs.get('image_type') == 'box_scans':
            _png(path)
            saved.append(url)
        return True

    monkeypatch.setattr(metadata_merger, 'download_ss_media', download)
    monkeypatch.setattr(metadata_merger, 'keep_screenshot_if_unique', lambda *a, **k: True)
    monkeypatch.setattr(metadata_merger, 'get_existing_screenshot_hashes', lambda *a, **k: [])
    full = dict(boxart='b', boxart_3d='b3', boxart_back='bb', fanart='f', game_logo='l',
                video='v', manual='m')
    full.update(stored)
    metadata = collections.defaultdict(lambda: None, full)
    metadata_merger.apply_screenscraper_to_metadata(
        metadata, {'medias': SS_MEDIA}, 4, {'filled_fields': []}, own_region='eu')
    return metadata, saved


def test_screenscraper_disc_nearest_the_games_region(monkeypatch, tmp_path):
    metadata, saved = _ss(monkeypatch, tmp_path, box_scans=None)
    assert saved == ['http://x/eu.png']
    entry = json.loads(metadata['box_scans'])['screenscraper']
    [item] = entry['items']
    assert item['kind'] == 'media' and (item['width'], item['height']) == (40, 70)
    assert item['file'].startswith('4_media_0_') and item['file'].endswith('.webp')
    assert os.path.isfile(tmp_path / 'box_scans' / item['file'])


def test_screenscraper_merges_into_a_mobygames_record_without_a_disc(monkeypatch, tmp_path):
    metadata, saved = _ss(monkeypatch, tmp_path, box_scans=json.dumps(_moby('front', 'back')))
    record = json.loads(metadata['box_scans'])
    assert saved == ['http://x/eu.png']
    assert [i['kind'] for i in record['mobygames']['items']] == ['front', 'back']
    assert record['screenscraper']['items'][0]['kind'] == 'media'


def test_screenscraper_leaves_a_record_that_has_a_disc(monkeypatch, tmp_path):
    stored = json.dumps(_moby('front', 'media'))
    metadata, saved = _ss(monkeypatch, tmp_path, box_scans=stored)
    assert saved == [] and metadata['box_scans'] == stored


def test_a_record_with_no_box_scans_slot_downloads_no_disc(monkeypatch, tmp_path):
    metadata, saved = _ss(monkeypatch, tmp_path)
    assert saved == [] and 'box_scans' not in metadata


def test_an_unreadable_download_is_deleted_and_not_recorded(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path))
    path = tmp_path / 'box_scans' / '4_media_0_ab.webp'
    path.parent.mkdir()
    path.write_bytes(b'not a picture')
    assert box_scans.media_entry(path.name) is None
    assert not path.exists()


def test_mobygames_merges_into_a_record_another_source_filled():
    ss = box_scans.with_source(None, 'screenscraper', {'items': [{'kind': 'media', 'file': 'a.webp'}]})
    both = box_scans.with_source(ss, 'mobygames', _moby('front')['mobygames'])
    assert box_scans.has_source(both, 'screenscraper') and box_scans.has_source(both, 'mobygames')
    # Fill-only per source: a second entry for a source already there is ignored.
    assert box_scans.with_source(both, 'mobygames', {'items': []}) == both


def test_the_open_box_shows_mobygames_disc_first_and_one_disc_only(monkeypatch, tmp_path):
    monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path))
    record = box_scans.with_source(None, 'screenscraper', {'items': [
        {'kind': 'media', 'file': '4_media_0_ss.webp'}]})
    record = box_scans.with_source(record, 'mobygames', _moby('media', 'manual')['mobygames'])
    for name in ('4_media_0_ss.webp', '4_manual_0_ab.webp'):
        _png(str(tmp_path / 'box_scans' / name))

    # MobyGames' disc file is missing, so ScreenScraper's shows.
    assert [s['url'] for s in box_scans.scans_for({'box_scans': record})] == [
        'images/box_scans/4_manual_0_ab.webp', 'images/box_scans/4_media_0_ss.webp']

    _png(str(tmp_path / 'box_scans' / '4_media_0_ab.webp'))
    assert [s['url'] for s in box_scans.scans_for({'box_scans': record})] == [
        'images/box_scans/4_media_0_ab.webp', 'images/box_scans/4_manual_0_ab.webp']


def test_esde_physical_media_fills_the_disc(library, later_source, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, 'IMAGE_PATH', library.images)
    library.gamelist(FATAL_RUN)
    _picture(os.path.join(library.media, 'physicalmedia', 'Fatal Run (USA).png'))
    library.add_game()

    result = _scrape()

    [item] = json.loads(library.row()['box_scans'])['esde']['items']
    assert item['kind'] == 'media' and (item['width'], item['height']) == (64, 64)
    with Image.open(library.image('box_scans', item['file'])) as image:
        assert image.format == 'WEBP'
    assert 'box_scans +1 (ES-DE)' in result['filled_fields']


def test_esde_leaves_a_game_that_has_a_disc(library, later_source, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, 'IMAGE_PATH', library.images)
    library.gamelist(FATAL_RUN)
    _picture(os.path.join(library.media, 'physicalmedia', 'Fatal Run (USA).png'))
    stored = json.dumps(_moby('media'))
    library.add_game(box_scans=stored)

    _scrape()

    assert library.row()['box_scans'] == stored
    assert not os.path.isdir(library.image('box_scans', ''))
