"""Browse buttons on path fields: services/path_browser.py and the admin route
behind them. The route lists any folder on the computer, so it is admin-only.
"""
import os
import re
from pathlib import Path

import pytest

from services import path_browser

_CSRF_TOKEN = 'tok'
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def tree(tmp_path):
    (tmp_path / 'Beta').mkdir()
    (tmp_path / 'alpha' / 'inner').mkdir(parents=True)
    (tmp_path / 'alpha' / 'file.txt').write_text('x')
    (tmp_path / '.config').mkdir()
    (tmp_path / 'retroarch').write_text('#!/bin/sh\n')
    return tmp_path


def _names(items):
    return [i['name'] for i in items]


def test_folders_sorted_hidden_last_files_left_out(tree):
    view = path_browser.list_path(str(tree))
    assert _names(view['folders']) == ['alpha', 'Beta', '.config']
    assert view['files'] == []
    alpha = view['folders'][0]
    assert alpha['path'] == str(tree / 'alpha')
    assert (alpha['file_count'], alpha['subfolder_count']) == (1, 1)
    assert view['current_path'] == str(tree)
    assert view['parent_path'] == str(tree.parent)


def test_files_listed_when_asked(tree):
    view = path_browser.list_path(str(tree), include_files=True)
    assert view['files'] == [{'name': 'retroarch', 'path': str(tree / 'retroarch')}]


def test_hidden_can_be_left_out(tree):
    view = path_browser.list_path(str(tree), include_hidden=False)
    assert '.config' not in _names(view['folders'])


def test_filesystem_root_has_no_parent():
    view = path_browser.list_path(os.path.abspath(os.sep))
    assert view['parent_path'] is None and view['is_root'] is True


def test_unreadable_folder_raises(tree, monkeypatch):
    def refuse(_path):
        raise PermissionError
    monkeypatch.setattr(path_browser.os, 'scandir', refuse)
    with pytest.raises(PermissionError):
        path_browser.list_path(str(tree))


@pytest.mark.parametrize('typed, expected', [
    ('alpha', 'alpha'),                 # a folder opens itself
    ('retroarch', ''),                  # a file opens the folder holding it
    ('alpha/gone/deeper', 'alpha'),     # the nearest folder that exists
])
def test_start_folder_from_what_was_typed(tree, typed, expected):
    assert path_browser.start_folder(str(tree / typed)) == str(tree / expected).rstrip(os.sep)


def test_start_folder_expands_home(monkeypatch, tree):
    monkeypatch.setenv('HOME', str(tree))
    assert path_browser.start_folder('~/alpha') == str(tree / 'alpha')


@pytest.mark.parametrize('typed', ['', None, 'flatpak run org.libretro.RetroArch'])
def test_start_folder_falls_back_to_home(monkeypatch, tree, typed):
    monkeypatch.setenv('HOME', str(tree))
    assert path_browser.start_folder(typed) == str(tree)


def test_windows_lists_its_drives(monkeypatch, tree):
    monkeypatch.setattr('platform_utils.IS_WINDOWS', True)
    real_isdir = os.path.isdir
    monkeypatch.setattr(path_browser.os.path, 'isdir',
                        lambda p: p in ('C:\\', 'D:\\') or real_isdir(p))
    assert path_browser.list_path(str(tree))['drives'] == ['C:\\', 'D:\\']


def test_other_systems_list_no_drives(monkeypatch, tree):
    monkeypatch.setattr('platform_utils.IS_WINDOWS', False)
    assert path_browser.list_path(str(tree))['drives'] == []


# -----------------------------------------------------------------------------
# The route
# -----------------------------------------------------------------------------

def _client(monkeypatch, role):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    monkeypatch.setattr('app.get_current_user',
                        lambda: {'id': 99, 'username': 'tester', 'role': role})
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = _CSRF_TOKEN
    return client


def _post(client, **body):
    return client.post('/api/settings/browse-paths', json=body,
                       headers={'X-CSRF-Token': _CSRF_TOKEN})


def test_route_lists_for_an_admin(monkeypatch, setup_complete, tree):
    rv = _post(_client(monkeypatch, 'admin'), path=str(tree), files=True)
    assert rv.status_code == 200, rv.data
    body = rv.get_json()
    assert body['current_path'] == str(tree)
    assert 'alpha' in _names(body['folders']) and _names(body['files']) == ['retroarch']


def test_route_opens_the_nearest_folder(monkeypatch, setup_complete, tree):
    rv = _post(_client(monkeypatch, 'admin'), path=str(tree / 'retroarch'))
    assert rv.get_json()['current_path'] == str(tree)


@pytest.mark.parametrize('role', ['viewer', 'editor', 'player'])
def test_route_refuses_everyone_else(monkeypatch, setup_complete, tree, role):
    assert _post(_client(monkeypatch, role), path=str(tree)).status_code == 403


def test_setup_browser_still_hides_hidden_folders(monkeypatch, tree):
    import app as app_module
    monkeypatch.setattr('app.settings_manager.load_settings', lambda: {})
    monkeypatch.setattr('app.config.ROM_PATH', '', raising=False)
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    rv = app_module.app.test_client().post('/api/setup/browse-folders', json={'path': str(tree)})
    assert rv.status_code == 200, rv.data
    assert _names(rv.get_json()['folders']) == ['alpha', 'Beta']


def test_setup_browser_closes_once_setup_is_done(monkeypatch):
    import app as app_module
    monkeypatch.setattr('app.settings_manager.load_settings', lambda: {'setup_completed': True})
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    rv = app_module.app.test_client().post('/api/setup/browse-folders', json={})
    assert rv.status_code == 403


# -----------------------------------------------------------------------------
# Every path field has a button
# -----------------------------------------------------------------------------

@pytest.mark.parametrize('template, field, scope', [
    ('_settings_tabs/library.html', 'romPathInput', 'folder'),
    ('_settings_tabs/scraping.html', 'esdeGamelistsInput', 'folder'),
    ('_settings_tabs/scraping.html', 'esdeMediaInput', 'folder'),
    ('_settings_tabs/scraping.html', 'rpcs3TrophyInput', 'folder'),
    ('_settings_tabs/account.html', 'userTrophyPath', 'folder'),
    ('rom_tools_settings.html', 'romsPath', 'folder'),
    ('rom_tools_settings.html', 'tempPath', 'folder'),
    ('rom_tools_settings.html', 'chdmanPath', 'file'),
    ('settings_emulators.html', 'ra-binary', 'file'),
    ('settings_emulators.html', 'ra-cores-dir', 'folder'),
    ('settings_emulators.html', 'cheat-import-path', 'folder'),
    ('settings_emulators.html', 'emu-folder-input', 'folder'),
    ('settings_emulators.html', 'emu_edit_binary_path_override', 'file'),
])
def test_path_field_has_a_browse_button(template, field, scope):
    text = (ROOT / 'templates' / template).read_text(encoding='utf-8')
    assert f'id="{field}"' in text
    assert re.search(rf"browse_button\('{re.escape(field)}', '{scope}'\)", text)


@pytest.mark.parametrize('role, shown', [('admin', True), ('viewer', False), ('editor', False)])
def test_only_an_admin_gets_the_button(role, shown):
    import app as app_module
    with app_module.app.test_request_context():
        macro = app_module.app.jinja_env.from_string(
            '{% from "_macros/browse_button.html" import browse_button with context %}'
            "{{ browse_button('x', 'folder') }}")
        assert ('openFolderBrowser' in macro.render(current_user={'role': role})) is shown

