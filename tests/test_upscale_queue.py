"""PASS-59-130 — a scrape saves small images as downloaded and lists the game;
the background worker upscales them later and clears the list
(docs/specs/image-pipeline.md §5.1)."""

import sqlite3

import pytest
from PIL import Image

import config
from services import image_utils, migrations, upscale_queue

GAME_ID = 7


@pytest.fixture
def queue_env(tmp_path, monkeypatch):
    db = tmp_path / 'roms.db'
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, boxart TEXT, "
                 "boxart_3d TEXT, screenshots TEXT)")
    migrations._load('019_pending_upscales').apply(conn)
    conn.execute("INSERT INTO games (id, screenshots) VALUES (?, ?)",
                 (GAME_ID, 'a.png,b.png'))
    conn.commit()
    conn.close()

    def _connect():
        c = sqlite3.connect(db)
        c.row_factory = sqlite3.Row
        return c

    monkeypatch.setattr(upscale_queue, '_connect', _connect)
    monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path))
    # No ESRGAN model in tests: the upscale path falls back to Lanczos.
    monkeypatch.setattr(image_utils, '_get_upscaler', lambda: None)
    (tmp_path / 'screenshots').mkdir()
    return tmp_path, _connect


def _image(path, height):
    Image.new('RGB', (height * 4 // 3, height), 'red').save(path)


def _height(path):
    with Image.open(path) as img:
        return img.size[1]


def _listed(connect):
    c = connect()
    try:
        return [tuple(r) for r in c.execute("SELECT game_id, queued_at FROM pending_upscales")]
    finally:
        c.close()


def test_scrape_leaves_small_image_and_lists_game(queue_env):
    tmp, connect = queue_env
    small = tmp / 'screenshots' / 'a.png'
    _image(small, 100)
    with upscale_queue.upscale_later(GAME_ID):
        image_utils.standardize_downloaded_image(str(small), 'screenshots')
    assert _height(small) == 100
    assert [g for g, _ in _listed(connect)] == [GAME_ID]


def test_scrape_still_downscales_a_large_image(queue_env):
    tmp, _ = queue_env
    big = tmp / 'screenshots' / 'a.png'
    _image(big, config.IMAGE_TARGET_HEIGHT * 3)
    with upscale_queue.upscale_later(GAME_ID):
        image_utils.standardize_downloaded_image(str(big), 'screenshots')
    assert _height(big) == config.IMAGE_TARGET_HEIGHT


def test_worker_upscales_listed_game_and_clears_it(queue_env):
    tmp, connect = queue_env
    for name in ('a.png', 'b.png'):
        _image(tmp / 'screenshots' / name, 100)
    upscale_queue.enqueue(GAME_ID)
    assert upscale_queue.run_pending() == 1
    for name in ('a.png', 'b.png'):
        assert _height(tmp / 'screenshots' / name) == config.IMAGE_TARGET_HEIGHT
    assert _listed(connect) == []


def test_game_listed_again_mid_run_keeps_its_row(queue_env):
    tmp, connect = queue_env
    _image(tmp / 'screenshots' / 'a.png', 100)
    upscale_queue.enqueue(GAME_ID)
    (_, stale), = _listed(connect)
    upscale_queue.enqueue(GAME_ID)  # a newer scrape of the same game
    upscale_queue.process_game(GAME_ID, stale)
    assert [g for g, _ in _listed(connect)] == [GAME_ID]
