"""PASS-59-119: ROM Tools defects found while writing docs/specs/rom-tools.md.

Riskiest first: Clean deleting every member, CHD convert replacing a .chd
or deleting an unverified source, duplicate delete removing every copy.
Then pause/cancel, the unguarded screenshot scan, the scanner registry,
the duplicate scan's `method`, the symlink guards and the staging folder.

No chdman or archive tool runs: subprocess calls are stubbed.
"""
import os
import re
import tempfile
import threading
import time
from types import SimpleNamespace

import pytest

from tests.test_pass59_rom_tools import _InlineThread, pages, rom_client  # noqa: F401


def _inline_threads(monkeypatch, thread_cls=_InlineThread):
    """Run routes.tools workers inline. Only routes.tools sees the stub: the
    rate limiter's own Timer thread must stay real."""
    import routes.tools as tools
    shim = SimpleNamespace(**{**vars(threading), 'Thread': thread_cls})
    monkeypatch.setattr(tools, 'threading', shim)


def _wait(cond, timeout=5.0):
    end = time.time() + timeout
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.02)
    return False


# --- Clean: a pattern list must never empty an archive ---------------------

@pytest.mark.parametrize('pattern', ['*', '*.*', '?*', '**', '*.'])
def test_match_everything_pattern_is_refused(pattern):
    from services.rom_tools_validators import validate_rom_tools_value
    ok, _reason, _cleaned = validate_rom_tools_value('unwanted_patterns', ['.txt', pattern])
    assert ok is False


@pytest.mark.parametrize('pattern', ['.txt', '*.nfo', 'readme*', 'file_id.diz'])
def test_ordinary_patterns_still_save(pattern):
    from services.rom_tools_validators import validate_rom_tools_value
    ok, _reason, cleaned = validate_rom_tools_value('unwanted_patterns', [pattern])
    assert ok is True and cleaned == [pattern]


def test_clean_never_removes_every_member(monkeypatch):
    from scraper.rom_tools import ArchiveScanner, ROMToolsConfig
    scanner = ArchiveScanner(ROMToolsConfig())
    removed = []
    monkeypatch.setattr(scanner, 'get_archive_contents_detailed', lambda _p: {
        'success': True, 'files': [{'name': 'Game.bin'}, {'name': 'readme.txt'}]})
    monkeypatch.setattr(scanner, 'remove_files_from_archive',
                        lambda _p, files: removed.extend(files) or {'success': True})
    result = scanner.clean_archive('/roms/Game.zip', ['*'])
    assert removed == []
    assert result['success'] is False


def test_clean_still_removes_the_unwanted_members(monkeypatch):
    from scraper.rom_tools import ArchiveScanner, ROMToolsConfig
    scanner = ArchiveScanner(ROMToolsConfig())
    removed = []
    monkeypatch.setattr(scanner, 'get_archive_contents_detailed', lambda _p: {
        'success': True, 'files': [{'name': 'Game.bin'}, {'name': 'readme.txt'}]})
    monkeypatch.setattr(scanner, 'remove_files_from_archive',
                        lambda _p, files: removed.extend(files) or {'success': True})
    scanner.clean_archive('/roms/Game.zip', ['.txt'])
    assert removed == ['readme.txt']


# --- CHD convert -----------------------------------------------------------

def _fake_chdman(monkeypatch, content=b'NEW'):
    """createcd writes `content` to its -o path; verify succeeds."""
    import scraper.rom_tools as rt

    def run(cmd, **_k):
        if cmd[1] == 'createcd':
            with open(cmd[cmd.index('-o') + 1], 'wb') as f:
                f.write(content)
        return type('R', (), {'returncode': 0, 'stderr': ''})()
    monkeypatch.setattr(rt.subprocess, 'run', run)


def test_unverified_conversion_keeps_the_source(tmp_path, monkeypatch):
    from scraper.rom_tools import convert_one_to_chd
    _fake_chdman(monkeypatch)
    src = tmp_path / 'Game.cue'
    src.write_bytes(b'cue')
    result = convert_one_to_chd(str(src), 'chdman', do_verify=False, delete_original=True)
    assert result['status'] == 'success'
    assert src.exists()


def test_verified_conversion_still_deletes_the_source(tmp_path, monkeypatch):
    from scraper.rom_tools import convert_one_to_chd
    _fake_chdman(monkeypatch)
    src = tmp_path / 'Game.cue'
    src.write_bytes(b'cue')
    convert_one_to_chd(str(src), 'chdman', do_verify=True, delete_original=True)
    assert not src.exists()


@pytest.mark.parametrize('skip_existing,expected', [(True, b'OLD'), (False, b'NEW')])
def test_convert_route_honours_skip_existing(rom_client, monkeypatch,  # noqa: F811
                                             skip_existing, expected):
    import routes.tools as tools
    post, roms = rom_client
    monkeypatch.setattr(tools.shutil, 'which', lambda _p: '/usr/bin/chdman')
    _inline_threads(monkeypatch)
    _fake_chdman(monkeypatch)
    (roms / 'Game.cue').write_bytes(b'cue')
    (roms / 'Game.chd').write_bytes(b'OLD')
    post('/api/rom-tools/chd-converter/convert',
         {'files': [str(roms / 'Game.cue')], 'skip_existing': skip_existing})
    assert (roms / 'Game.chd').read_bytes() == expected


# --- Duplicate delete: the server keeps one copy of every group ------------

@pytest.fixture
def dup_group(rom_client):  # noqa: F811
    import routes.tools as tools
    post, roms = rom_client
    a, b = roms / 'Game (USA).sfc', roms / 'Game (Europe).sfc'
    for f in (a, b):
        f.write_bytes(b'same')
    task_id = 'dup-59119'
    tools._rom_tool_tasks[task_id] = {
        'task_id': task_id, 'task_type': 'duplicate_scan', 'status': 'completed',
        'results': {'groups': [{'files': [{'path': str(a)}, {'path': str(b)}]}]},
        'logs': []}
    yield post, task_id, a, b
    tools._rom_tool_tasks.pop(task_id, None)


def test_duplicate_delete_refuses_the_last_copy(dup_group):
    post, task_id, a, b = dup_group
    post('/api/rom-tools/duplicate-finder/delete',
         {'task_id': task_id, 'files': [str(a), str(b)]})
    assert a.exists() and b.exists()


def test_duplicate_delete_needs_the_scan(dup_group):
    post, _task_id, a, b = dup_group
    resp = post('/api/rom-tools/duplicate-finder/delete', {'files': [str(a)]})
    assert resp.status_code == 400
    assert resp.get_json()['success'] is False
    assert a.exists()


def test_duplicate_delete_skips_a_file_the_scan_did_not_group(dup_group):
    post, task_id, a, _b = dup_group
    other = a.parent / 'Other Game.sfc'
    other.write_bytes(b'x')
    resp = post('/api/rom-tools/duplicate-finder/delete',
                {'task_id': task_id, 'files': [str(other)]})
    assert resp.get_json()['results']['deleted'] == 0
    assert other.exists()


def test_duplicate_delete_removes_a_spare_copy(dup_group):
    post, task_id, a, b = dup_group
    resp = post('/api/rom-tools/duplicate-finder/delete',
                {'task_id': task_id, 'files': [str(a)]})
    assert resp.get_json()['results']['deleted'] == 1
    assert not a.exists() and b.exists()


# --- Pause and cancel on the routes registry -------------------------------

def test_paused_verify_waits_and_can_be_cancelled(rom_client, monkeypatch):  # noqa: F811
    import routes.tools as tools
    post, roms = rom_client
    monkeypatch.setattr(tools.shutil, 'which', lambda _p: '/usr/bin/chdman')
    files = []
    for name in ('a.chd', 'b.chd'):
        (roms / name).write_bytes(b'x')
        files.append(str(roms / name))
    gate, calls = threading.Event(), []

    def run(cmd, **_k):
        calls.append(cmd[-1])
        if len(calls) == 1:
            gate.wait(5)
        return type('R', (), {'returncode': 0})()
    monkeypatch.setattr(tools.subprocess, 'run', run)

    task_id = post('/api/rom-tools/chd-verify/verify', {'files': files}).get_json()['task_id']
    task = tools._rom_tool_tasks[task_id]
    try:
        assert _wait(lambda: len(calls) == 1)
        assert post(f'/api/rom-tools/task/{task_id}/pause', {}).status_code == 200
        gate.set()
        time.sleep(0.3)
        assert len(calls) == 1, 'a paused task went on to the next file'
        assert post(f'/api/rom-tools/task/{task_id}/cancel', {}).status_code == 200
        assert _wait(lambda: task.get('end_time') is not None)
        assert task['status'] == 'cancelled'
        assert len(calls) == 1
    finally:
        gate.set()
        task['status'] = 'cancelled'


def test_scanner_registry_cancels_a_paused_task():
    from scraper.rom_tools import cancel_task, create_task, update_task
    task = create_task('scan')
    task.status = 'paused'
    update_task(task)
    assert cancel_task(task.task_id) is True
    assert task.status == 'cancelled'


# --- Screenshot dedup scan runs guarded -------------------------------------

def test_screenshot_scan_crash_marks_the_task_failed(rom_client, monkeypatch):  # noqa: F811
    import routes.tools as tools
    post, _roms = rom_client

    def boom(*_a, **_k):
        raise RuntimeError('db gone')
    monkeypatch.setattr(tools, 'query', boom)
    resp = post('/api/rom-tools/screenshot-dedup/scan', {'method': 'hash'})
    task = tools._rom_tool_tasks[resp.get_json()['task_id']]
    _wait(lambda: task['status'] != 'running', timeout=2)
    assert task['status'] == 'failed'
    assert task.get('end_time') is not None


# --- Scanner registry: full ids, finished tasks reaped ---------------------

def test_scanner_task_ids_are_full_uuids():
    from scraper.rom_tools import create_task
    assert re.fullmatch(r'[0-9a-f-]{36}', create_task('scan').task_id)


def test_scanner_registry_reaps_old_finished_tasks():
    import scraper.rom_tools as rt
    old = rt.create_task('scan')
    old.status, old.end_time = 'completed', time.time() - 7200
    running = rt.create_task('scan')
    running.status, running.end_time = 'running', 0
    rt.create_task('scan')
    assert rt.get_task(old.task_id) is None
    assert rt.get_task(running.task_id) is running


# --- Duplicate scan: method checked, symlinks out of the root ignored -------

def test_duplicate_scan_refuses_an_unknown_method(rom_client, monkeypatch):  # noqa: F811
    import routes.tools as tools
    post, roms = rom_client
    _inline_threads(monkeypatch)
    resp = post('/api/rom-tools/duplicate-finder/scan', {'path': str(roms), 'method': 'size'})
    assert resp.status_code == 400


@pytest.mark.parametrize('recursive', [True, False])
def test_duplicate_scan_skips_files_linked_from_outside(rom_client, monkeypatch,  # noqa: F811
                                                        tmp_path, recursive):
    import routes.tools as tools
    post, roms = rom_client
    _inline_threads(monkeypatch)
    outside = tmp_path / 'outside'
    outside.mkdir()
    (outside / 'Secret.sfc').write_bytes(b'same')
    for name in ('Game (USA).sfc', 'Game (Europe).sfc'):
        (roms / name).write_bytes(b'same')
    (roms / 'Linked.sfc').symlink_to(outside / 'Secret.sfc')
    resp = post('/api/rom-tools/duplicate-finder/scan',
                {'path': str(roms), 'method': 'hash', 'recursive': recursive})
    task = tools._rom_tool_tasks[resp.get_json()['task_id']]
    names = {f['name'] for g in task['results']['groups'] for f in g['files']}
    assert names == {'Game (USA).sfc', 'Game (Europe).sfc'}


@pytest.mark.parametrize('finder', ['archives', 'roms'])
def test_non_recursive_finders_skip_links_out_of_the_root(tmp_path, finder):
    from pathlib import Path
    from scraper.rom_tools import ArchiveScanner, DuplicateFinder, ROMToolsConfig
    roms, outside = tmp_path / 'roms', tmp_path / 'outside'
    roms.mkdir()
    outside.mkdir()
    ext = '.zip' if finder == 'archives' else '.sfc'
    (roms / f'Inside{ext}').write_bytes(b'x')
    (outside / f'Secret{ext}').write_bytes(b'x')
    (roms / f'Linked{ext}').symlink_to(outside / f'Secret{ext}')
    cfg = ROMToolsConfig(recursive_scan=False, archive_types=['.zip'])
    found = (ArchiveScanner(cfg)._find_archives(Path(roms)) if finder == 'archives'
             else DuplicateFinder(cfg)._find_rom_files(Path(roms)))
    assert [p.name for p in found] == [f'Inside{ext}']


# --- Browse folders: the parent link stays inside the root ------------------

def test_browse_parent_link_stays_inside_the_root(rom_client, tmp_path):  # noqa: F811
    post, roms = rom_client
    (roms / 'Sub').mkdir()
    sibling = tmp_path / 'roms_other'
    sibling.mkdir()
    (sibling / 'lnk').symlink_to(roms / 'Sub', target_is_directory=True)
    resp = post('/api/rom-tools/browse-folders', {'path': str(sibling / 'lnk')})
    assert resp.get_json()['parent_path'] is None


# --- Staging: never the system temp dir by default ---------------------------

@pytest.mark.parametrize('temp_path', ['', os.path.join(tempfile.gettempdir(), 'retrodb_romtools')])
def test_default_staging_is_not_the_system_temp_dir(temp_path):
    from scraper.rom_tools import ArchiveScanner, ROMToolsConfig
    folder = ArchiveScanner(ROMToolsConfig(temp_path=temp_path))._staging_folder()
    assert not folder.startswith(tempfile.gettempdir())


def test_default_config_names_no_temp_path():
    from scraper.rom_tools import ROMToolsConfig
    assert ROMToolsConfig().temp_path == ''


# --- Pages: the settings reset and the archive scanner's staging text -------

def test_settings_reset_names_only_elements_on_the_page(pages):  # noqa: F811
    html = pages('/tools/settings', {})
    body = html[html.index('function resetDefaults()'):]
    body = body[:body.index('\n}\n')]
    ids = set(re.findall(r"getElementById\('([^']+)'\)", body))
    assert ids
    assert {i for i in ids if f'id="{i}"' not in html} == set()


def test_archive_scanner_shows_no_fixed_staging_path(pages):  # noqa: F811
    html = pages('/tools/archive-scanner', {})
    assert 'ROMS_TO_BE_DELETED' not in html
    batch = html[html.index("showConfirm('💿 Batch M3U'"):]
    batch = batch[:batch.index('async function()')]
    assert 'staging folder' in batch
