"""PASS-59-146 — Full Re-scrape starts with an empty screenshot list. A source's
own earlier screenshot, still on disk, must be listed again, not skipped and
left on disk unlisted."""
import collections
import os

import pytest

import scraper.image_dedup as dedup
import scraper.metadata_merger as mod

GAME_ID = 320


@pytest.fixture
def image_dir(tmp_path, monkeypatch):
    os.makedirs(tmp_path / 'screenshots')
    monkeypatch.setattr(mod, 'IMAGE_PATH', str(tmp_path))
    monkeypatch.setattr(dedup, 'IMAGE_PATH', str(tmp_path))
    # No network: every new download fails, so only on-disk files can be listed.
    monkeypatch.setattr(mod, '_download_and_finalize', lambda *a, **k: False)
    return tmp_path


def _on_disk(image_dir, stem, ext):
    name = f"{stem}{mod.preferred_image_extension('screenshots', ext)}"
    (image_dir / 'screenshots' / name).write_bytes(b'not really an image')
    return name


def _empty_metadata():
    return collections.defaultdict(lambda: None)


def _result():
    return {'filled_fields': []}


def test_igdb_relists_its_screenshot(image_dir):
    name = _on_disk(image_dir, f'{GAME_ID}_igdb_ss1', '.jpg')
    metadata = _empty_metadata()
    data = {'screenshots': [{'url': '//img/t_thumb/a.jpg'}, {'url': '//img/t_thumb/b.jpg'}]}
    mod.apply_igdb_to_metadata(metadata, data, GAME_ID, _result())
    assert metadata['screenshots'] == name


def test_rawg_relists_its_screenshot(image_dir):
    name = _on_disk(image_dir, f'{GAME_ID}_rawg_ss1', '.jpg')
    metadata = _empty_metadata()
    data = {'screenshot_urls': ['https://img/a.jpg', 'https://img/b.jpg']}
    mod.apply_rawg_to_metadata(metadata, data, GAME_ID, _result())
    assert metadata['screenshots'] == name


def test_screenscraper_relists_its_screenshot(image_dir):
    name = _on_disk(image_dir, f'{GAME_ID}_ss_screenshot_0', '.png')
    metadata = _empty_metadata()
    data = {'medias': [{'type': 'ss', 'url': 'https://img/a', 'format': 'png'},
                       {'type': 'ss', 'url': 'https://img/b', 'format': 'png'}]}
    mod.apply_screenscraper_to_metadata(metadata, data, GAME_ID, _result())
    assert metadata['screenshots'] == name


def test_listed_screenshot_is_not_listed_twice(image_dir):
    name = _on_disk(image_dir, f'{GAME_ID}_rawg_ss1', '.jpg')
    metadata = _empty_metadata()
    metadata['screenshots'] = name
    data = {'screenshot_urls': ['https://img/a.jpg']}
    mod.apply_rawg_to_metadata(metadata, data, GAME_ID, _result())
    assert metadata['screenshots'] == name
