# PASS-59-108 — Apply Metadata progress gauge: the tracker's percentage math,
# its reach into the screenshot download pool, and the start/poll routes.
import time

import pytest

from services import apply_progress


def _wait(task, timeout=5.0):
    deadline = time.monotonic() + timeout
    while not task.finished and time.monotonic() < deadline:
        time.sleep(0.01)
    assert task.finished, "apply task never finished"


# -----------------------------------------------------------------------------
# Tracker
# -----------------------------------------------------------------------------

def test_percent_is_steps_done_over_planned():
    task = apply_progress.ApplyTask(1)
    task.plan(4)
    task.step_done()
    assert task.snapshot()['percent'] == 25


def test_download_in_flight_counts_its_byte_fraction():
    task = apply_progress.ApplyTask(1)
    task.plan(1)                      # 1 planned + 1 download = 2 steps
    key = object()
    task.download_start(key, 'video', 1000)
    task.download_bytes(key, 500)
    snap = task.snapshot()
    assert snap['percent'] == 25      # (0 done + 0.5) / 2
    assert snap['step'] == {'kind': 'download', 'media': 'video'}
    task.download_end(key)
    assert task.snapshot()['percent'] == 50


def test_percent_never_moves_backwards_when_the_plan_grows():
    task = apply_progress.ApplyTask(1)
    task.plan(2)
    task.step_done()
    assert task.snapshot()['percent'] == 50
    task.plan(8)                      # 1/10 would read 10
    assert task.snapshot()['percent'] == 50


def test_unplan_drops_steps_that_will_not_run():
    task = apply_progress.ApplyTask(1)
    task.plan(4)
    task.step_done()
    task.unplan(2)
    assert task.snapshot()['percent'] == 50


def test_held_below_100_until_finish():
    task = apply_progress.ApplyTask(1)
    task.plan(1)
    task.step_done()
    assert task.snapshot()['percent'] == 99
    task.finish(result={'success': True})
    snap = task.snapshot()
    assert snap['percent'] == 100 and snap['finished'] and snap['applied']


def test_image_processing_is_its_own_step(tmp_path, monkeypatch):
    """Upscaling after a download can take longer than the download, so it
    shows as 'process' while it runs and counts as a step when done."""
    import services.image_utils as iu
    seen = []
    monkeypatch.setattr(iu, '_ensure_format_matches_extension', lambda p: None)
    monkeypatch.setattr(iu, 'standardize_downloaded_image',
                        lambda p, t: seen.append(apply_progress._current.get().snapshot()['step']))
    monkeypatch.setattr(iu, '_make_responsive_variants', lambda p, t: None)
    img = tmp_path / 'screenshots' / 'a.webp'
    img.parent.mkdir()
    img.write_bytes(b'x')

    task = apply_progress.start(1, iu.finalize_downloaded_image, str(img), 'screenshots')
    _wait(task)
    assert task.error is None
    assert seen == [{'kind': 'process'}]
    assert task._done == 1 and task._planned == 1


def test_helpers_are_noops_without_an_active_task():
    apply_progress.plan(3)
    apply_progress.begin('fetch', source='IGDB')
    apply_progress.step_done()
    with apply_progress.download('/x/videos/a.mp4', 10) as dl:
        dl.received(10)


@pytest.mark.parametrize('path, kind', [
    ('/m/boxart/a.webp', 'boxart'),
    ('/m/boxart_3d/a.webp', 'boxart_3d'),
    ('/m/screenshots/a.webp', 'screenshot'),
    ('/m/videos/a.mp4', 'video'),
    ('/m/manuals/a.pdf', 'manual'),
    ('/m/other/a.bin', 'media'),
])
def test_media_kind_from_destination_folder(path, kind):
    assert apply_progress.media_kind(path) == kind


def test_tracker_reaches_the_parallel_screenshot_pool():
    """Pool threads do not inherit a ContextVar; the per-job context copy in
    _download_screenshots_parallel is what carries the tracker in."""
    from scraper.metadata_merger import _download_screenshots_parallel

    def job():
        with apply_progress.download('/m/screenshots/a.webp', 10) as dl:
            dl.received(10)
        return None   # falsy: phase 2's dedup skips it

    task = apply_progress.start(
        1, _download_screenshots_parallel, [job, job, job], set(), 'TEST')
    _wait(task)
    assert task.error is None
    assert task._done == 3 and task._planned == 3


def test_an_exception_in_the_apply_becomes_the_task_error():
    def boom():
        raise RuntimeError('upstream down')

    task = apply_progress.start(1, boom)
    _wait(task)
    assert task.error == 'upstream down'
    assert task.snapshot()['applied'] is False


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

CSRF = {'X-CSRF-Token': 'test-csrf-token'}


@pytest.fixture
def editor_client(monkeypatch):
    import app as mod
    monkeypatch.setitem(mod.app.config, 'TESTING', True)
    monkeypatch.setattr('app.get_current_user',
                        lambda: {'id': 99, 'username': 'tester', 'role': 'editor'})
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    monkeypatch.setattr('app.settings_manager.load_settings',
                        lambda: {'setup_completed': True, 'rom_path': '/tmp'})
    monkeypatch.setattr('routes.games.query',
                        lambda *a, **k: {'id': 1, 'system_folder': 'snes'})
    client = mod.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'test-csrf-token'
    return client


def _start(client, **body):
    return client.post('/api/game/1/apply-metadata', json=body, headers=CSRF)


def test_apply_runs_in_background_and_flashes_once_on_success(editor_client, monkeypatch):
    calls = []

    def fake_apply(**kwargs):
        calls.append(kwargs)
        return {'success': True, 'sources_used': ['IGDB'],
                'filled_fields': ['genre', 'developer'], 'missing_fields': []}

    monkeypatch.setattr('routes.games.apply_hybrid_metadata_to_game', fake_apply)
    rv = _start(editor_client, game_source='igdb_1234',
                secondary_selections=[{'source': 'tgdb', 'id': '9', 'name': 'X'}])
    assert rv.status_code == 200
    task_id = rv.get_json()['task_id']
    _wait(apply_progress.get(task_id))

    assert calls[0]['primary_source'] == 'igdb'
    assert calls[0]['primary_id'] == '1234'
    assert calls[0]['system_folder'] == 'snes'
    assert calls[0]['explicit_secondary'] == [{'source': 'tgdb', 'id': '9', 'name': 'X'}]

    body = editor_client.get(f'/api/apply-metadata/{task_id}').get_json()
    assert body['finished'] and body['applied'] and body['percent'] == 100
    editor_client.get(f'/api/apply-metadata/{task_id}')
    with editor_client.session_transaction() as sess:
        flashes = sess.get('_flashes', [])
    assert len(flashes) == 1
    assert flashes[0][0] == 'success' and 'IGDB' in flashes[0][1]


def test_apply_with_nothing_ticked_sends_an_empty_selection(editor_client, monkeypatch):
    """PASS-59-134: an empty list, not None, so only the clicked source and
    AI fill gaps; no stale session results are passed."""
    calls = []
    monkeypatch.setattr('routes.games.apply_hybrid_metadata_to_game',
                        lambda **k: calls.append(k) or {'success': True})
    rv = _start(editor_client, game_source='igdb_1234')
    _wait(apply_progress.get(rv.get_json()['task_id']))
    assert calls[0]['explicit_secondary'] == []
    assert 'all_results' not in calls[0]

def test_a_poll_mid_apply_is_a_successful_request_not_a_failure(editor_client, monkeypatch):
    """The envelope's `success` means the request worked; the apply's own
    outcome is `applied`. Sharing one key made every mid-run poll read as a
    failed apply and closed the gauge at once."""
    import threading
    release = threading.Event()

    def slow_apply(**kwargs):
        release.wait(5)
        return {'success': True}

    monkeypatch.setattr('routes.games.apply_hybrid_metadata_to_game', slow_apply)
    task_id = _start(editor_client, game_source='igdb_1').get_json()['task_id']
    try:
        body = editor_client.get(f'/api/apply-metadata/{task_id}').get_json()
        assert body['success'] is True
        assert body['finished'] is False and body['applied'] is False
    finally:
        release.set()
        _wait(apply_progress.get(task_id))


def test_a_failed_apply_reports_an_error_and_flashes_nothing(editor_client, monkeypatch):
    monkeypatch.setattr('routes.games.apply_hybrid_metadata_to_game',
                        lambda **k: {'success': False})
    task_id = _start(editor_client, game_source='tgdb_5').get_json()['task_id']
    _wait(apply_progress.get(task_id))
    body = editor_client.get(f'/api/apply-metadata/{task_id}').get_json()
    assert body['finished'] and not body['applied'] and body['error']
    with editor_client.session_transaction() as sess:
        assert not sess.get('_flashes')


def test_apply_without_a_selection_is_rejected(editor_client):
    rv = _start(editor_client, game_source='igdb')
    assert rv.status_code == 400
    assert rv.get_json()['success'] is False


def test_unknown_task_is_404(editor_client):
    rv = editor_client.get('/api/apply-metadata/nope')
    assert rv.status_code == 404
    assert rv.get_json()['success'] is False
