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
