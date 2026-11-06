"""PASS-59-249 group G: the image pipeline.

Each test pins one finding from the 2026-11-04 audit
(docs/reviews/close-findings-2026-11-05-pass-59-249.md, group G).
"""
import contextlib
import io
import os
import queue
import sqlite3
import sys
import threading
import time
import types
from collections import namedtuple

import pytest
from PIL import Image

import config
from services import box_faces, image_utils, media_cleanup, upscale_queue
from tests.test_box_faces import _box, _png, game, images  # noqa: F401  (fixtures)
from tests.test_webp_migrate import webp_env  # noqa: F401  (a fixture)


# --- GIFs are not upscaled ------------------------------------------------------

def test_a_small_gif_is_not_sent_to_the_upscaler(tmp_path, monkeypatch):
    from services.jobs.image_resize import _standardize_with_tracking
    path = tmp_path / 'tiny.gif'
    Image.new('P', (40, 30)).save(path, 'GIF')
    called = []
    monkeypatch.setattr(image_utils, '_upscale_image', lambda *a: called.append(1))
    image_utils.standardize_image(str(path), 'boxart', 1000)
    assert _standardize_with_tracking(str(path), 'boxart', 1000, False) == 'skipped'
    assert called == []


# --- The model download --------------------------------------------------------

def _fake_model_site(monkeypatch, body):
    import requests
    from services import ssrf
    monkeypatch.setattr(ssrf, 'validate_outbound_url', lambda *a, **k: (True, '', None))
    monkeypatch.setattr(ssrf, 'validate_and_pin_url', lambda _r, url, **k: (url, '203.0.113.1', None))
    monkeypatch.setattr(ssrf, 'pin_host_ip', lambda *a: contextlib.nullcontext())

    class _Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def raise_for_status(self):
            pass

        def iter_content(self, chunk_size):
            yield body
    monkeypatch.setattr(requests, 'get', lambda *a, **k: _Resp())


def test_the_default_model_must_match_its_published_hash(tmp_path, monkeypatch):
    _fake_model_site(monkeypatch, b'<html>error page</html>')
    dest = tmp_path / 'model.onnx'
    with pytest.raises(RuntimeError):
        image_utils._download_model(image_utils._MODEL_URLS[0], str(dest))
    assert not dest.exists()


def test_a_bad_cached_model_is_downloaded_again(tmp_path, monkeypatch):
    monkeypatch.setattr(os.path, 'expanduser', lambda p: str(tmp_path) if p == '~' else p)
    monkeypatch.setattr(config, 'REALESRGAN_MODEL_NAME', 'probe', raising=False)
    monkeypatch.setattr(config, 'REALESRGAN_MODEL_URL', image_utils._MODEL_URLS[0], raising=False)
    cached = tmp_path / '.cache' / 'realesrgan' / 'probe.onnx'
    cached.parent.mkdir(parents=True)
    cached.write_bytes(b'<html>error page</html>')
    downloads = []
    monkeypatch.setattr(image_utils, '_download_model', lambda url, dest: downloads.append(dest))

    def _session(*a, **k):
        raise RuntimeError('not a model')
    monkeypatch.setitem(sys.modules, 'onnxruntime', types.SimpleNamespace(
        InferenceSession=_session, get_available_providers=lambda: ['CPUExecutionProvider']))
    monkeypatch.setattr(image_utils, '_upscaler', None)
    image_utils._init_upscaler(allow_gpu=False)
    assert downloads == [str(cached)]


# --- The upscale queue stays in its folder -------------------------------------

def test_the_upscale_queue_ignores_a_name_outside_its_folder(tmp_path, monkeypatch):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, boxart TEXT, boxart_3d TEXT, screenshots TEXT)")
    conn.execute("INSERT INTO games VALUES (1, '../../outside.png', NULL, 'ok.png,../x.png')")
    monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path))
    names = [os.path.basename(p) for p, _ in upscale_queue._media_files(conn, 1)]
    assert names == ['ok.png']


# --- The mass-missing guard ------------------------------------------------------

def test_a_folder_holding_only_variants_and_temp_files_is_not_healthy(tmp_path):
    for name in ('12_tgdb-sm.webp', '12_tgdb-md.webp', '.save_abc.tmp'):
        (tmp_path / name).write_bytes(b'x')
    assert not media_cleanup.media_dir_is_healthy(str(tmp_path))
    (tmp_path / '13_tgdb.webp').write_bytes(b'x')
    assert media_cleanup.media_dir_is_healthy(str(tmp_path))


# --- The GPU circuit breaker -------------------------------------------------------

def test_a_gpu_call_after_the_breaker_trips_fails_fast(monkeypatch):
    monkeypatch.setattr(image_utils, '_GPU_RUN_TIMEOUT', 3)
    stopped = queue.Queue()      # nobody serves it, as after the breaker trips
    monkeypatch.setattr(image_utils, '_gpu_queue', stopped)
    threading.Timer(0.2, lambda: setattr(image_utils, '_gpu_queue', None)).start()
    started = time.monotonic()
    with pytest.raises(RuntimeError):
        image_utils._gpu_run(object(), {})
    assert time.monotonic() - started < 2


def test_a_gpu_upscaler_never_runs_its_session_off_the_gpu_thread(monkeypatch):
    import numpy as np
    ran = []
    session = types.SimpleNamespace(
        get_inputs=lambda: [types.SimpleNamespace(name='x', shape=[1, 3, 'h', 'w'])],
        run=lambda *a: ran.append(threading.current_thread().name))
    monkeypatch.setattr(image_utils, '_gpu_queue', None)
    upscaler = image_utils._OnnxUpscaler(session, tile_size=8, tile_pad=0, gpu=True)
    with pytest.raises(RuntimeError):
        upscaler.enhance(np.zeros((8, 8, 3), dtype=np.uint8))
    assert ran == []


# --- Transparency on the upscale path --------------------------------------------

@pytest.mark.parametrize('mode', ['LA', 'P'])
def test_an_upscale_keeps_transparency_beyond_rgba(monkeypatch, mode):
    import numpy as np

    class _Fake:
        _gpu = False

        def enhance(self, arr, outscale=4):
            return np.kron(arr, np.ones((4, 4, 1), dtype=arr.dtype)), None
    monkeypatch.setattr(image_utils, '_get_upscaler', lambda: _Fake())
    img = Image.new(mode, (20, 20))
    if mode == 'P':
        img.info['transparency'] = 0
    result = image_utils._upscale_image(img, 'controllers', 60, preserve_rgba=True)
    assert result.mode in ('RGBA', 'LA', 'PA')


# --- Box faces -------------------------------------------------------------------

def test_two_faces_naming_one_upload_both_import(game, images):  # noqa: F811
    one = io.BytesIO(_png(270, 380))
    uploads = {'S.box.json': _box(faces={'front': 'S.png', 'spine': 'S.spine.png', 'back': 'S.png'}),
               'S.png': one, 'S.spine.png': _png(28, 380)}
    record = box_faces.import_box_file(game, uploads)
    assert record is not None


def test_removing_an_unreadable_record_removes_its_files(game, images):  # noqa: F811
    from services.database import execute
    box_faces.import_box_file(game, {
        'S.box.json': _box(), 'S.front.png': _png(270, 380),
        'S.spine.png': _png(28, 380), 'S.back.png': _png(270, 380)})
    folder = images / 'box_faces'
    assert any(n.startswith(f'{game}_') for n in os.listdir(folder))
    execute("UPDATE games SET box_faces = 'not json' WHERE id = ?", (game,))
    assert box_faces.remove_box_faces(game)
    assert not any(n.startswith(f'{game}_') for n in os.listdir(folder))


# --- WebP migration ----------------------------------------------------------------

def test_webp_migration_takes_back_covers_and_logos(webp_env):  # noqa: F811
    from services.jobs.webp_migrate import _build_work_list
    webp_env['write_image']('boxart_back', 'b.jpg')
    webp_env['write_image']('game_logos', 'l.png', fmt='PNG')
    webp_env['insert_game'](boxart_back='b.jpg', game_logo='l.png')
    items, _ = _build_work_list()
    assert sorted((it['column'], it['filename']) for it in items) == [
        ('boxart_back', 'b.jpg'), ('game_logo', 'l.png')]


def test_webp_disk_guard_needs_room_for_one_file_not_the_library(webp_env, monkeypatch):  # noqa: F811
    from services.jobs import webp_migrate as mod
    for i in range(4):
        webp_env['write_image']('boxart', f'g{i}.jpg')
        webp_env['insert_game'](boxart=f'g{i}.jpg')
    items, total = mod._build_work_list()
    largest = max(os.path.getsize(it['full_path']) for it in items)
    usage = namedtuple('DiskUsage', ['total', 'used', 'free'])
    monkeypatch.setattr(mod.shutil, 'disk_usage', lambda _: usage(0, 0, 2 * largest + 1))
    assert 2 * largest + 1 < 2 * total
    for name in ('persist_job_start', 'persist_job_progress', 'persist_job_complete'):
        monkeypatch.setattr(mod, name, lambda *a, **k: 'id')
    monkeypatch.setattr(mod, 'resolve_terminal_status', lambda *a, **k: 'completed')
    monkeypatch.setattr(mod, 'acquire_job_singleton_lock', lambda _: 0)
    monkeypatch.setattr(mod, 'release_singleton_fd', lambda *_a, **_k: None)
    monkeypatch.setattr(image_utils, '_get_upscaler', lambda: None)
    job = mod.WebPMigrateJob()
    job._worker()
    assert job.get_status()['error_message'] is None
