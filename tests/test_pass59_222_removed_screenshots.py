"""PASS-59-222 — a screenshot the user removed stays removed when the game is
scraped again. Deleting one keeps its picture's dHash; every merge then drops
a download or ES-DE copy that looks the same."""
import collections
import os
import random

import pytest
from PIL import Image

import scraper.image_dedup as dedup
import scraper.metadata_merger as mod
from services.database import execute


def _picture(path, seed):
    """Seeded noise: the same seed gives the same picture, another seed one
    that looks unrelated."""
    rng = random.Random(seed)
    img = Image.new('L', (9, 8))
    img.putdata([rng.randrange(256) for _ in range(72)])
    img.resize((90, 80), Image.NEAREST).save(path)


@pytest.fixture
def game(tmp_path, monkeypatch, setup_complete):
    import config
    os.makedirs(tmp_path / 'screenshots')
    for m in (mod, dedup, config):
        monkeypatch.setattr(m, 'IMAGE_PATH', str(tmp_path))
    system_id = execute("INSERT INTO systems (name, folder) VALUES ('RemovedShotProbe', 'removedshotprobe')")
    gid = execute("INSERT INTO games (title, system_id, rom_path) "
                  "VALUES ('Removed Shot Probe', ?, 'probe.bin')", (system_id,))
    name = f'{gid}_ss1.png'
    execute("UPDATE games SET screenshots = ? WHERE id = ?", (name, gid))
    _picture(tmp_path / 'screenshots' / name, seed=1)
    yield gid, name, tmp_path
    execute("DELETE FROM games WHERE id = ?", (gid,))
    execute("DELETE FROM systems WHERE id = ?", (system_id,))


def test_delete_remembers_the_picture(game, admin_test_client):
    gid, name, _dir = game
    client, csrf = admin_test_client()
    resp = client.post(f'/api/delete-screenshot/{gid}', json={'screenshot': name},
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert len(dedup.removed_hashes(gid)) == 1


def test_a_rescrape_does_not_bring_it_back(game, admin_test_client, monkeypatch):
    gid, name, image_dir = game
    client, csrf = admin_test_client()
    client.post(f'/api/delete-screenshot/{gid}', json={'screenshot': name},
                headers={'X-CSRF-Token': csrf})

    # RAWG "downloads" the same picture again, then a different one.
    seeds = iter([1, 9])

    def fake_download(url, path, *a, **k):
        _picture(path, seed=next(seeds))
        return True
    monkeypatch.setattr(mod, '_download_and_finalize', fake_download)
    monkeypatch.setattr(mod, 'per_game_screenshots_fit', lambda *a: True)

    metadata = collections.defaultdict(lambda: None)
    data = {'screenshot_urls': ['https://img/a.jpg', 'https://img/b.jpg'], 'platforms': [{'id': 26}]}
    mod.apply_rawg_to_metadata(metadata, data, gid, {'filled_fields': []})
    kept = [s for s in (metadata['screenshots'] or '').split(',') if s]
    assert len(kept) == 1, kept
    assert dedup.compute_dhash(image_dir / 'screenshots' / kept[0]) != \
        dedup.removed_hashes(gid)[0][1]


def test_the_record_goes_with_the_game(game):
    gid, name, image_dir = game
    dedup.remember_removed(gid, image_dir / 'screenshots' / name)
    execute("DELETE FROM games WHERE id = ?", (gid,))
    assert dedup.removed_hashes(gid) == []


def test_esde_does_not_copy_it_back(game, admin_test_client, monkeypatch):
    """ES-DE's screenshot keeps one fixed name, so before PASS-59-222 a deleted
    one was copied straight back by the next scrape."""
    import scraper.scrape_esde as esde
    gid, name, image_dir = game
    client, csrf = admin_test_client()
    client.post(f'/api/delete-screenshot/{gid}', json={'screenshot': name},
                headers={'X-CSRF-Token': csrf})

    media = image_dir / 'esde_media'
    (media / 'screenshots').mkdir(parents=True)
    _picture(media / 'screenshots' / 'probe.png', seed=1)   # the removed picture
    (media / 'titlescreens').mkdir()
    _picture(media / 'titlescreens' / 'probe.png', seed=9)  # one never removed
    monkeypatch.setattr(esde, 'IMAGE_PATH', str(image_dir))
    monkeypatch.setattr(esde, '_get_esde_gamelists_path', lambda: None)
    monkeypatch.setattr(esde, '_find_esde_media_base', lambda *a: str(media))
    # The real one loads the GPU upscaler, which aborts at interpreter exit.
    monkeypatch.setattr('services.image_utils.standardize_downloaded_image', lambda *a, **k: None)

    copied = esde.copy_esde_media(gid, {}, existing={'screenshots': ''})
    assert copied.get('screenshots') == [f'{gid}_esde_ts.png'], copied
