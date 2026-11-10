"""PASS-59-284: emulator folders split on the OS list separator.

Split on ':', every Windows folder broke at its drive letter (C:\\Emu became
'C' and '\\Emu'). The list now splits like PATH: ';' on Windows, ':' here.
"""

from pathlib import Path


def test_windows_folders_survive(monkeypatch):
    import routes.launch_settings as ls
    monkeypatch.setattr(ls.os, 'pathsep', ';')
    monkeypatch.setattr(ls, 'get_setting', lambda key, default=None: r'C:\Emu;D:\Games\Emulators')
    assert ls._scan_paths() == [Path(r'C:\Emu'), Path(r'D:\Games\Emulators')]


def test_linux_folders_unchanged(monkeypatch):
    import routes.launch_settings as ls
    monkeypatch.setattr(ls.os, 'pathsep', ':')
    monkeypatch.setattr(ls, 'get_setting', lambda key, default=None: '/mnt/Emulators:/opt')
    assert ls._scan_paths() == [Path('/mnt/Emulators'), Path('/opt')]


def test_page_gets_the_separator():
    from tests._util import read_source
    assert 'data-sep="{{ path_list_separator }}"' in read_source('templates/settings_emulators.html')
    assert "split(pathSep)" in read_source('static/js/emulators-settings.js')
