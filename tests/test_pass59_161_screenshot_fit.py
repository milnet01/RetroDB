"""PASS-59-161: the colour-count refusal at download, and the review scan."""
import os
import random
import sys
import threading
from types import SimpleNamespace

import pytest
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services import screenshot_fit as fit
from scraper import base_scraper
from tests.test_pass59_rom_tools import _InlineThread, rom_client  # noqa: F401


def _picture(path, colours, size=(256, 192), fmt='PNG'):
    """A picture holding exactly `colours` different colours, noise-scattered."""
    rng = random.Random(1)
    palette = [(i % 256, (i * 7) % 256, (i // 256) * 40) for i in range(colours)]
    im = Image.new('RGB', size)
    pixels = [palette[i] if i < colours else rng.choice(palette)
              for i in range(size[0] * size[1])]
    im.putdata(pixels)
    im.save(path, fmt)
    return str(path)


@pytest.mark.parametrize('folder, colours, refused', [
    ('zxspectrum', 15, False),
    ('zxspectrum', 32, False),   # the limit itself is allowed
    ('zxspectrum', 33, True),
    ('c64', 16, False),
    ('c64', 300, True),
    ('gb', 4, False),
    ('gb', 16, False),
    ('gb', 17, True),
])
def test_exact_colour_count_decides(tmp_path, folder, colours, refused):
    path = _picture(tmp_path / 'shot.png', colours)
    assert fit.has_impossible_colours(path, folder) is refused


@pytest.mark.parametrize('name, kwargs', [
    ('lossy format proves nothing', {'fmt': 'JPEG'}),
    ('a scaled original proves nothing', {'size': (640, 480)}),
])
def test_uncertain_originals_are_kept(tmp_path, name, kwargs):
    path = _picture(tmp_path / 'shot.img', 300, **kwargs)
    assert fit.has_impossible_colours(path, 'zxspectrum') is False, name


def test_unchecked_system_and_unreadable_file_are_kept(tmp_path):
    many = _picture(tmp_path / 'many.png', 300)
    assert fit.has_impossible_colours(many, 'snes') is False
    junk = tmp_path / 'junk.png'
    junk.write_bytes(b'not an image')
    assert fit.has_impossible_colours(str(junk), 'zxspectrum') is False


class _FakeConn:
    """Stands in for the scraper's connection and answers the folder lookup."""
    def __init__(self, folder):
        self.folder = folder

    def execute(self, *_args):
        return SimpleNamespace(fetchone=lambda: {'folder': self.folder} if self.folder else None)

    def close(self):
        pass


@pytest.mark.parametrize('folder, colours, refused', [
    ('zxspectrum', 300, True),
    ('zxspectrum', 15, False),
    ('snes', 300, False),
    (None, 300, False),   # game row gone: nothing to judge against
])
def test_game_lookup_feeds_the_check(tmp_path, monkeypatch, folder, colours, refused):
    monkeypatch.setattr(base_scraper, 'get_scraper_conn', lambda: _FakeConn(folder))
    path = _picture(tmp_path / 'shot.png', colours)
    assert base_scraper.screenshot_impossible_for_game(path, 7) is refused


class _FakeResponse:
    status_code = 200
    headers = {}

    def __init__(self, body):
        self.body = body

    def iter_content(self, chunk_size):
        return [self.body]

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


@pytest.fixture
def served_picture(tmp_path, monkeypatch):
    """Serve a 300-colour PNG to the download helpers, offline, for a Spectrum game."""
    import contextlib
    import services.ssrf as ssrf
    source = _picture(tmp_path / 'source.png', 300)
    with open(source, 'rb') as f:
        body = f.read()
    monkeypatch.setattr(ssrf, 'validate_outbound_url', lambda url: (True, None, None))
    monkeypatch.setattr(ssrf, 'validate_and_pin_url', lambda s, url, **kw: (url, '1.1.1.1', None))
    monkeypatch.setattr(ssrf, 'pin_host_ip', lambda *a: contextlib.nullcontext())
    monkeypatch.setattr(base_scraper._http_session, 'get', lambda *a, **kw: _FakeResponse(body))
    monkeypatch.setattr(base_scraper, 'get_scraper_conn', lambda: _FakeConn('zxspectrum'))
    # Finalizing can start the upscaler; these tests are about what comes before.
    import services.image_utils as image_utils
    from scraper import metadata_merger as merger
    monkeypatch.setattr(image_utils, 'finalize_downloaded_image', lambda *a: None)
    monkeypatch.setattr(merger, 'finalize_downloaded_image', lambda *a: None)
    folder = tmp_path / 'screenshots'
    folder.mkdir()
    return folder


def _leftovers(folder):
    return sorted(os.listdir(folder))


def test_download_image_refuses_and_leaves_nothing(served_picture):
    dest = served_picture / 'shot.png'
    assert base_scraper.download_image('https://x/a.png', str(dest), screenshot_of=7) is False
    assert _leftovers(served_picture) == []


def test_download_and_finalize_refuses_and_leaves_nothing(served_picture):
    from scraper import metadata_merger as merger
    dest = served_picture / 'shot.png'
    assert merger._download_and_finalize(
        'https://x/a.png', str(dest), 'screenshots', screenshot_of=7) is False
    assert _leftovers(served_picture) == []


def test_download_without_a_game_is_unchecked(served_picture):
    dest = served_picture / 'shot.png'
    assert base_scraper.download_image('https://x/a.png', str(dest)) is True
    assert _leftovers(served_picture) == ['shot.png']


def test_review_scan_ranks_worst_first_and_counts_unreadable(rom_client, monkeypatch, tmp_path):  # noqa: F811
    import routes.tools as tools
    post, _roms = rom_client
    shots = tmp_path / 'images' / 'screenshots'
    shots.mkdir(parents=True)
    _picture(shots / 'few.png', 15)
    many = Image.new('RGB', (256, 192))
    many.putdata([(x % 256, y % 256, (x * y) % 256) for y in range(192) for x in range(256)])
    many.save(shots / 'many.png')
    monkeypatch.setattr(tools.config, 'IMAGE_PATH', str(tmp_path / 'images'))
    monkeypatch.setattr(tools, 'query', lambda *_a, **_k: [
        {'id': 1, 'title': 'Game', 'screenshots': 'few.png, many.png,gone.png'}])
    monkeypatch.setattr(tools, 'threading', SimpleNamespace(**{**vars(threading), 'Thread': _InlineThread}))

    resp = post('/api/rom-tools/screenshot-review/scan', {'system': 'zxspectrum'})
    task = tools._rom_tool_tasks[resp.get_json()['task_id']]

    assert task['status'] == 'completed'
    assert [s['filename'] for s in task['results']['shots']] == ['many.png', 'few.png']
    assert task['results']['unreadable'] == 1


def test_review_scan_refuses_an_unchecked_system(rom_client):  # noqa: F811
    post, _roms = rom_client
    resp = post('/api/rom-tools/screenshot-review/scan', {'system': 'snes'})
    assert resp.status_code == 400
