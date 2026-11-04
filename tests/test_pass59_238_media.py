# =============================================================================
# PASS-59-238 — media files are never lost
# =============================================================================
# Regression pins for the audit 2026-11-04 media findings. Each test was red
# before its fix.
# =============================================================================

import os

import config
from services.database import get_db


def _wishlist_row(**cols):
    db = get_db()
    names = ['title'] + list(cols)
    cur = db.execute(
        f"INSERT INTO wishlist ({', '.join(names)}) VALUES ({', '.join('?' * len(names))})",
        ['Wish 238', *cols.values()],
    )
    db.commit()
    return cur.lastrowid


def _drop_wishlist(item_id):
    db = get_db()
    db.execute("DELETE FROM wishlist WHERE id = ?", [item_id])
    db.commit()


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as fh:
        fh.write(b'x')
    return path


def _preview_names(client):
    resp = client.get('/api/orphaned-media/preview')
    body = resp.get_json()
    assert isinstance(body.get('files'), list), body
    return {f['filename'] for f in body['files']}


class TestOrphanSweepKeepsWishlistFiles:
    """The sweep spared only files named after a game id, so every wishlist
    picture (named w<item id>_...) was listed and deleted."""

    def test_preview_spares_live_wishlist_files(self, admin_test_client):
        item_id = _wishlist_row()
        live = _touch(os.path.join(config.IMAGE_PATH, 'boxart', f'w{item_id}_boxart.png'))
        gone = _touch(os.path.join(config.IMAGE_PATH, 'boxart', f'w{item_id + 1000}_boxart.png'))
        try:
            client, _csrf = admin_test_client()
            names = _preview_names(client)
            assert os.path.basename(live) not in names
            # A wishlist item that no longer exists leaves a real orphan.
            assert os.path.basename(gone) in names
        finally:
            _drop_wishlist(item_id)
            for p in (live, gone):
                if os.path.exists(p):
                    os.remove(p)

    def test_preview_spares_file_a_wishlist_row_names(self, admin_test_client):
        name = 'renamed_wish_cover_238.png'
        item_id = _wishlist_row(boxart=name)
        path = _touch(os.path.join(config.IMAGE_PATH, 'boxart', name))
        try:
            client, _csrf = admin_test_client()
            assert name not in _preview_names(client)
        finally:
            _drop_wishlist(item_id)
            os.remove(path)


def _game_with_screenshots(value):
    db = get_db()
    sys_id = db.execute("SELECT id FROM systems LIMIT 1").fetchone()
    if sys_id is None:
        sys_id = db.execute(
            "INSERT INTO systems (name, folder) VALUES ('Test 238', 'test238')").lastrowid
    else:
        sys_id = sys_id[0]
    game_id = db.execute(
        "INSERT INTO games (title, rom_path, system_id, screenshots) VALUES (?, ?, ?, ?)",
        ['Shots 238', f'test238/shots238-{os.urandom(4).hex()}.bin', sys_id, value]).lastrowid
    db.commit()
    return game_id


def _stored_screenshots(game_id):
    return get_db().execute(
        "SELECT screenshots FROM games WHERE id = ?", [game_id]).fetchone()[0]


def _drop_game(game_id):
    db = get_db()
    db.execute("DELETE FROM games WHERE id = ?", [game_id])
    db.commit()


class TestViewsNeverClearScreenshotLists:
    """Opening a game (page or modal) wrote the screenshot list back without
    the files it could not find. With the picture folder unmounted, every
    game anyone opened lost its whole list."""

    def _point_images_at(self, tmp_path, monkeypatch):
        images = tmp_path / 'images'
        (images / 'screenshots').mkdir(parents=True)
        monkeypatch.setattr(config, 'IMAGE_PATH', str(images))
        return images / 'screenshots'

    def test_unmounted_folder_keeps_list_and_shows_it(self, tmp_path, monkeypatch,
                                                      admin_test_client):
        self._point_images_at(tmp_path, monkeypatch)   # empty = looks unmounted
        game_id = _game_with_screenshots('a238.png, b238.png')
        try:
            client, _csrf = admin_test_client()
            body = client.get(f'/api/game/{game_id}/detail').get_json()
            assert body['game']['screenshots'] == ['a238.png', 'b238.png']
            client.get(f'/game/{game_id}')
            assert _stored_screenshots(game_id) == 'a238.png, b238.png'
        finally:
            _drop_game(game_id)

    def test_healthy_folder_hides_missing_file_but_keeps_record(self, tmp_path, monkeypatch,
                                                                admin_test_client):
        shots = self._point_images_at(tmp_path, monkeypatch)
        _touch(str(shots / 'a238.png'))
        game_id = _game_with_screenshots('a238.png, b238.png')
        try:
            client, _csrf = admin_test_client()
            body = client.get(f'/api/game/{game_id}/detail').get_json()
            assert body['game']['screenshots'] == ['a238.png']
            client.get(f'/game/{game_id}')
            assert _stored_screenshots(game_id) == 'a238.png, b238.png'
        finally:
            _drop_game(game_id)


class _FakeResponse:
    def __init__(self, status, headers=None, chunks=()):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks

    def iter_content(self, chunk_size=8192):
        return iter(self._chunks)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_network(monkeypatch, response):
    import contextlib
    from services import ssrf
    from scraper import base_scraper
    monkeypatch.setattr(ssrf, 'validate_outbound_url', lambda url: (True, None, None))
    monkeypatch.setattr(ssrf, 'validate_and_pin_url',
                        lambda session, url, **kw: (url, '127.0.0.1', None))
    monkeypatch.setattr(ssrf, 'pin_host_ip', lambda host, ip: contextlib.nullcontext())
    monkeypatch.setattr(base_scraper._http_session, 'get', lambda *a, **kw: response)


class TestDownloadLeavesNoTempFile:
    """Early returns inside the download left a .dl_* file beside the media."""

    def _run(self, tmp_path, monkeypatch, response):
        from scraper.metadata_merger import _download_and_finalize
        _fake_network(monkeypatch, response)
        target = tmp_path / 'boxart' / '1_boxart.png'
        assert _download_and_finalize('https://example.invalid/a.png', str(target), 'boxart') is False
        return sorted(p.name for p in (tmp_path / 'boxart').iterdir())

    def test_http_error(self, tmp_path, monkeypatch):
        assert self._run(tmp_path, monkeypatch, _FakeResponse(404)) == []

    def test_declared_too_big(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, 'MAX_MEDIA_DOWNLOAD_BYTES', 10, raising=False)
        assert self._run(tmp_path, monkeypatch,
                         _FakeResponse(200, {'Content-Length': '999'})) == []

    def test_stream_too_big(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, 'MAX_MEDIA_DOWNLOAD_BYTES', 10, raising=False)
        assert self._run(tmp_path, monkeypatch,
                         _FakeResponse(200, chunks=[b'x' * 8, b'x' * 8])) == []


class _BrokenStream(_FakeResponse):
    def iter_content(self, chunk_size=8192):
        yield b'partial'
        raise ConnectionError('dropped')


class TestVideoManualDownloadKeepsOldFile:
    """Videos and manuals were written straight over the file a game uses, so
    a failed download destroyed the copy the game already had."""

    def _existing(self, tmp_path):
        target = tmp_path / 'manuals' / '1_ss_manual.pdf'
        target.parent.mkdir(parents=True)
        target.write_bytes(b'old manual')
        return target

    def _assert_kept(self, target):
        assert target.read_bytes() == b'old manual'
        assert sorted(p.name for p in target.parent.iterdir()) == [target.name]

    def test_dropped_connection(self, tmp_path, monkeypatch):
        from scraper.metadata_merger import download_ss_media
        target = self._existing(tmp_path)
        _fake_network(monkeypatch, _BrokenStream(200))
        assert download_ss_media('https://example.invalid/m.pdf', str(target), timeout=1) is False
        self._assert_kept(target)

    def test_over_size_cap(self, tmp_path, monkeypatch):
        from scraper.metadata_merger import download_ss_media
        target = self._existing(tmp_path)
        monkeypatch.setattr(config, 'MAX_MEDIA_DOWNLOAD_BYTES', 10, raising=False)
        _fake_network(monkeypatch, _FakeResponse(200, chunks=[b'x' * 8, b'x' * 8]))
        assert download_ss_media('https://example.invalid/m.pdf', str(target), timeout=1) is False
        self._assert_kept(target)

    def test_success_replaces(self, tmp_path, monkeypatch):
        from scraper.metadata_merger import download_ss_media
        target = self._existing(tmp_path)
        _fake_network(monkeypatch, _FakeResponse(200, chunks=[b'new manual']))
        assert download_ss_media('https://example.invalid/m.pdf', str(target), timeout=1) is True
        assert target.read_bytes() == b'new manual'
        assert sorted(p.name for p in target.parent.iterdir()) == [target.name]


from tests.test_webp_migrate import webp_env  # noqa: E402,F401 — fixture


def _run_webp_job():
    from services.jobs.webp_migrate import _build_work_list, _migrate_one
    items, _ = _build_work_list()
    return [(_migrate_one(item)[0], item['game_id']) for item in items]


class TestWebpMigrateKeepsFiles:
    def test_two_rows_sharing_a_file_both_point_at_the_webp(self, webp_env):
        webp_env['write_image']('boxart', 'shared.jpg')
        a = webp_env['insert_game'](boxart='shared.jpg')
        b = webp_env['insert_game'](boxart='shared.jpg')
        _run_webp_job()
        boxart = webp_env['tmp'] / 'images' / 'boxart'
        assert (boxart / 'shared.webp').is_file()
        assert webp_env['read_game'](a)['boxart'] == 'shared.webp'
        assert webp_env['read_game'](b)['boxart'] == 'shared.webp'

    def test_name_leaving_the_folder_is_not_touched(self, webp_env):
        outside = webp_env['tmp'] / 'outside.jpg'
        from PIL import Image
        Image.new('RGB', (10, 10)).save(outside, format='JPEG')
        game_id = webp_env['insert_game'](boxart='../../outside.jpg')
        _run_webp_job()
        assert outside.is_file()
        assert not (webp_env['tmp'] / 'outside.webp').exists()
        assert webp_env['read_game'](game_id)['boxart'] == '../../outside.jpg'


from tests.test_upscale_queue import queue_env, GAME_ID  # noqa: E402,F401 — fixture


class TestUpscalerNeverOverwritesNewerDownload:
    """The upscaler asked only whether the game still named the file, so an
    old picture, upscaled, was saved over a newer download of the same name."""

    def test_new_download_mid_upscale_survives(self, queue_env, monkeypatch):
        from PIL import Image
        from services import image_utils, upscale_queue
        tmp, _connect = queue_env
        shot = tmp / 'screenshots' / 'a.png'
        Image.new('RGB', (133, 100), 'red').save(shot)
        upscale_queue.enqueue(GAME_ID)
        real_upscale = image_utils._upscale_image

        def new_download_during_upscale(*args):
            fresh = tmp / 'screenshots' / '.dl_fresh'
            Image.new('RGB', (133, 100), 'blue').save(fresh, format='PNG')
            os.replace(fresh, shot)       # how every download lands
            return real_upscale(*args)

        monkeypatch.setattr(image_utils, '_upscale_image', new_download_during_upscale)
        upscale_queue.run_pending()
        with Image.open(shot) as img:
            assert img.convert('RGB').getpixel((0, 0)) == (0, 0, 255)


class TestImageSaves:
    def test_saved_image_is_readable_by_others(self, tmp_path):
        """mkstemp's 0600 survived the rename, so a web server or another
        account could not read any image RetroDB had saved."""
        from PIL import Image
        from services.image_utils import _save_image
        path = tmp_path / 'x.png'
        _save_image(Image.new('RGB', (8, 8)), str(path))
        assert path.stat().st_mode & 0o777 == 0o644

    def test_failed_save_reports_false(self, tmp_path, monkeypatch):
        from PIL import Image
        from services import image_utils

        def boom(*a, **kw):
            raise OSError('disk full')
        monkeypatch.setattr(image_utils, '_atomic_save', boom)
        assert image_utils._save_image(Image.new('RGB', (8, 8)), str(tmp_path / 'x.png')) is False

    def test_resize_job_counts_a_failed_save_as_failed(self, tmp_path, monkeypatch):
        """The resize job counted an image whose save failed as upscaled."""
        import pytest
        from PIL import Image
        from services import image_utils
        from services.jobs.image_resize import _standardize_with_tracking
        monkeypatch.setattr(image_utils, '_get_upscaler', lambda: None)

        def boom(*a, **kw):
            raise OSError('disk full')
        monkeypatch.setattr(image_utils, '_atomic_save', boom)
        path = tmp_path / 'small.png'
        Image.new('RGB', (40, 30)).save(path)
        with pytest.raises(OSError):
            _standardize_with_tracking(str(path), 'screenshots', 1080, False)


class TestDeleteRemovesOwnMedia:
    """Deleting a game or a wishlist item left all its pictures on disk.
    A file another row still names must stay."""

    def _boxart(self, name):
        return _touch(os.path.join(config.IMAGE_PATH, 'boxart', name))

    def test_delete_game_removes_its_files_but_not_shared_ones(self, admin_test_client):
        own = self._boxart('del238_own.png')
        shared = self._boxart('del238_shared.png')
        victim = _game_with_screenshots(None)
        keeper = _game_with_screenshots(None)
        db = get_db()
        db.execute("UPDATE games SET boxart = ?, fanart = ? WHERE id = ?",
                   ['del238_own.png', 'del238_shared.png', victim])
        db.execute("UPDATE games SET boxart = ? WHERE id = ?", ['del238_shared.png', keeper])
        db.commit()
        try:
            client, csrf = admin_test_client()
            resp = client.delete(f'/api/delete-game/{victim}', headers={'X-CSRF-Token': csrf})
            assert resp.get_json()['success'] is True
            assert not os.path.exists(own)
            assert os.path.exists(shared)
        finally:
            _drop_game(victim)
            _drop_game(keeper)
            for p in (own, shared):
                if os.path.exists(p):
                    os.remove(p)

    def test_delete_wishlist_item_removes_its_files(self, admin_test_client):
        own = self._boxart('w238_boxart.png')
        item_id = _wishlist_row(boxart='w238_boxart.png', owner_id=1)
        try:
            client, csrf = admin_test_client()
            resp = client.delete(f'/api/wishlist/{item_id}', headers={'X-CSRF-Token': csrf})
            assert resp.get_json()['success'] is True
            assert not os.path.exists(own)
        finally:
            _drop_wishlist(item_id)
            if os.path.exists(own):
                os.remove(own)
