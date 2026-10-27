"""Uploaded covers, fanart and screenshots go through the scraper's image
pipeline: the configured format, size standardization, the responsive
variants, and for screenshots the perceptual-hash duplicate check."""
import io
import os

import pytest
from PIL import Image, ImageDraw
from werkzeug.datastructures import FileStorage

import config
from services import game_media_service as gms

GAME_ID = 990417


def _png(size, pattern=0):
    img = Image.new('RGB', size, (20, 40, 60))
    draw = ImageDraw.Draw(img)
    w, h = size
    for i in range(8):
        x = (i * w // 8 + pattern * w // 5) % w
        draw.rectangle([x, 0, x + w // 16, h], fill=(250, 200 - 20 * i, 30 * pattern))
    draw.ellipse([w // 4, h // 4, w // 2 + pattern * w // 6, 3 * h // 4], fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, 'PNG')
    return buf.getvalue()


def _upload(raw, name='cover.png'):
    return FileStorage(stream=io.BytesIO(raw), filename=name)


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    for sub in ('boxart', 'fanart', 'screenshots'):
        folder = os.path.join(config.IMAGE_PATH, sub)
        for name in os.listdir(folder) if os.path.isdir(folder) else []:
            if name.startswith(f'{GAME_ID}_'):
                os.remove(os.path.join(folder, name))


def test_cover_is_converted_resized_and_given_variants(monkeypatch):
    monkeypatch.setattr(config, 'IMAGE_FORMAT', 'webp')
    folder = gms.image_dir('boxart')
    name = gms.save_upload(_upload(_png((1800, 2400))), folder, GAME_ID, 'custom',
                           gms.ALLOWED_IMAGE_EXT, image_type='boxart')
    assert name == f'{GAME_ID}_custom.webp'
    with Image.open(os.path.join(folder, name)) as img:
        assert img.format == 'WEBP'
        assert img.height == config.IMAGE_TARGET_HEIGHT
    for suffix in ('sm', 'md'):
        assert os.path.exists(os.path.join(folder, f'{GAME_ID}_custom-{suffix}.webp'))


def test_without_a_type_the_upload_is_kept_as_is():
    folder = gms.image_dir('boxart')
    name = gms.save_upload(_upload(_png((300, 400))), folder, GAME_ID, 'raw',
                           gms.ALLOWED_IMAGE_EXT)
    assert name == f'{GAME_ID}_raw.png'


def test_screenshot_duplicates_are_dropped(monkeypatch):
    monkeypatch.setattr(config, 'IMAGE_FORMAT', 'webp')
    first = _png((640, 480), pattern=0)
    other = _png((640, 480), pattern=3)
    csv, dupes = gms.save_screenshots([_upload(first, 'a.png')], GAME_ID, '')
    assert csv == f'{GAME_ID}_ss1.webp' and dupes == 0

    # The same shot again (bigger, so resized), plus a different one.
    bigger = io.BytesIO()
    Image.open(io.BytesIO(first)).resize((1280, 960)).save(bigger, 'PNG')
    csv, dupes = gms.save_screenshots(
        [_upload(bigger.getvalue(), 'b.png'), _upload(other, 'c.png')], GAME_ID, csv)
    assert dupes == 1
    assert csv.split(',') == [f'{GAME_ID}_ss1.webp', f'{GAME_ID}_ss2.webp']
    folder = gms.image_dir('screenshots')
    assert sorted(n for n in os.listdir(folder) if n.startswith(f'{GAME_ID}_')) \
        == [f'{GAME_ID}_ss1.webp', f'{GAME_ID}_ss2.webp']
    with Image.open(os.path.join(folder, f'{GAME_ID}_ss2.webp')) as img:
        assert img.format == 'WEBP'


def test_remove_media_file_takes_the_variants_too(monkeypatch):
    monkeypatch.setattr(config, 'IMAGE_FORMAT', 'webp')
    folder = gms.image_dir('boxart')
    name = gms.save_upload(_upload(_png((600, 800))), folder, GAME_ID, 'custom',
                           gms.ALLOWED_IMAGE_EXT, image_type='boxart')
    gms.remove_media_file(name, 'boxart')
    assert not [n for n in os.listdir(folder) if n.startswith(f'{GAME_ID}_')]
