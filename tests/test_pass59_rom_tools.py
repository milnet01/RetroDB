"""Pass 59.49: saved ROM Tools settings are the tool pages' defaults.

Decision (2026-09-26, user): each tool page opens with its tick-boxes preset
from the saved settings, a run may change them, and the server uses the
run's value, falling back to the saved one.

Before this, `ROMToolsConfig.from_dict` had no callers, the Duplicate Finder
and CHD pages ignored the saved settings, the CHD page's three tick-boxes were
never sent (the server always used the saved values, so unticking "Delete
original files" did not stop a delete), and `temp_path` had no reader.
"""
import re

import pytest

from tests._util import read_source

_CSRF = 'tok'


@pytest.fixture
def pages(monkeypatch):
    import app as app_module
    user = {'id': 1, 'username': 'admin', 'role': 'admin'}
    monkeypatch.setattr('app.get_current_user', lambda: user)
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    monkeypatch.setattr('app.settings_manager.load_settings',
                        lambda: {'setup_completed': True, 'rom_path': '/tmp'})

    import routes.tools
    original = routes.tools.load_rom_tools_config

    def get(path, saved):
        import routes.tools as tools
        base = original()
        monkeypatch.setattr(tools, 'load_rom_tools_config', lambda: {**base, **saved})
        resp = app_module.app.test_client().get(path)
        assert resp.status_code == 200, resp.status_code
        return resp.get_data(as_text=True)
    return get


def _checked(html, element_id):
    tag = re.search(rf'<input[^>]*id="{element_id}"[^>]*>', html)
    assert tag, element_id
    return re.search(r'\schecked(\s|>|=)', tag.group(0)) is not None


def test_run_option_prefers_the_request_then_the_setting():
    from routes.tools import _run_option
    saved = {'chd_delete_originals': True}
    assert _run_option({'delete_originals': False}, 'delete_originals',
                       saved, 'chd_delete_originals', False) is False
    assert _run_option({}, 'delete_originals', saved, 'chd_delete_originals', False) is True
    assert _run_option({}, 'delete_originals', {}, 'chd_delete_originals', False) is False
    # A non-boolean from the request is not trusted as a choice.
    assert _run_option({'delete_originals': 'yes'}, 'delete_originals',
                       {}, 'chd_delete_originals', False) is False


def test_duplicate_finder_page_presets_from_settings(pages):
    html = pages('/tools/duplicate-finder', {'ignore_region_tags': False, 'include_archives': True})
    assert not _checked(html, 'optIgnoreRegion')
    assert _checked(html, 'optArchives')


def test_chd_page_presets_from_settings(pages):
    html = pages('/tools/chd-converter', {'chd_verify_after_convert': False,
                                          'chd_delete_originals': True,
                                          'chd_skip_existing': False})
    assert not _checked(html, 'optVerify')
    assert _checked(html, 'optDelete')
    assert not _checked(html, 'optSkip')


def test_chd_page_sends_its_tick_boxes():
    src = read_source('templates/chd_converter.html')
    for key in ('skip_existing', 'verify', 'delete_originals'):
        assert re.search(rf'\b{key}\s*:', src), f"CHD page never sends {key}"


def test_routes_build_the_scanner_config_from_saved_settings():
    src = read_source('routes/tools.py')
    assert 'ROMToolsConfig()' not in src
    assert 'ROMToolsConfig.from_dict(' in src


def test_m3u_staging_follows_temp_path(tmp_path):
    from scraper.rom_tools import ArchiveScanner, ROMToolsConfig
    scanner = ArchiveScanner(ROMToolsConfig(temp_path=str(tmp_path)))
    assert scanner._staging_folder().startswith(str(tmp_path))


# --- PASS-59-51: the live scan endpoints refuse symlinks out of the ROM root ---

@pytest.fixture
def rom_client(tmp_path, monkeypatch):
    """An admin test client whose ROM root is an empty tmp folder.

    Returns (post, roms): post(route, body) sends a CSRF-valid JSON POST.
    """
    import app as app_module
    import settings_manager as _settings_manager
    roms = tmp_path / 'roms'
    roms.mkdir()
    user = {'id': 1, 'username': 'admin', 'role': 'admin'}
    monkeypatch.setattr(app_module, 'get_current_user', lambda: user)
    monkeypatch.setattr(app_module, 'get_user_settings', lambda _uid: None)
    monkeypatch.setattr(_settings_manager, 'load_settings',
                        lambda: {'setup_completed': True})
    monkeypatch.setattr(_settings_manager, 'get_effective_path',
                        lambda key, fallback='': str(roms))
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = _CSRF

    def post(route, body):
        return client.post(route, json=body, headers={'X-CSRF-Token': _CSRF})
    return post, roms


@pytest.fixture
def escaping_rom_root(rom_client, tmp_path):
    """A ROM root holding one real image and a symlink to a folder outside it."""
    post, roms = rom_client
    outside = tmp_path / 'outside'
    outside.mkdir()
    for name in ('inside.chd', 'disc.iso'):
        (roms / name).write_bytes(b'x')
    for name in ('escaped.chd', 'escaped_disc.iso'):
        (outside / name).write_bytes(b'x')
    (roms / 'link').symlink_to(outside, target_is_directory=True)

    def scan(route):
        resp = post(route, {'path': str(roms)})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:200]
        return {f['name'] for f in resp.get_json()['files']}
    return scan


@pytest.mark.parametrize('route,inside', [
    ('/api/rom-tools/chd-verify/scan', 'inside.chd'),
    ('/api/rom-tools/chd-converter/scan', 'disc.iso'),
])
def test_scan_skips_files_reached_through_an_escaping_symlink(
        escaping_rom_root, route, inside):
    names = escaping_rom_root(route)
    assert inside in names
    assert not any(n.startswith('escaped') for n in names), names


def test_extracted_folder_walk_is_guarded():
    src = read_source('scraper/rom_tools.py')
    walk = src.index('extract_folder.rglob(')
    assert '_safe_under_root(' in src[walk:walk + 300]


# --- PASS-59-56: a worker that hits an error ends its task, never hangs it ---

class _InlineThread:
    """Runs the worker inside start(), so the test sees its end state."""
    def __init__(self, target):
        self._target = target
        self.daemon = True

    def start(self):
        self._target()


def test_verify_survives_a_file_deleted_before_its_turn(rom_client, monkeypatch):
    import routes.tools as tools
    post, roms = rom_client
    monkeypatch.setattr(tools.shutil, 'which', lambda _p: '/usr/bin/chdman')
    monkeypatch.setattr(tools.threading, 'Thread', _InlineThread)
    present = roms / 'present.chd'
    present.write_bytes(b'x')
    monkeypatch.setattr(tools.subprocess, 'run',
                        lambda *a, **k: type('R', (), {'returncode': 0})())

    resp = post('/api/rom-tools/chd-verify/verify',
                {'files': [str(roms / 'gone.chd'), str(present)]})
    task = tools._rom_tool_tasks[resp.get_json()['task_id']]
    assert task['status'] == 'completed'
    assert task['results']['valid'] == 1
    assert task['results']['invalid'] == 1


def test_worker_crash_marks_the_task_failed():
    import routes.tools as tools
    task = {'status': 'running', 'logs': []}

    def body():
        raise RuntimeError('boom')
    tools._guarded_worker(task, body)()
    assert task['status'] == 'failed'
    assert task['end_time'] is not None
