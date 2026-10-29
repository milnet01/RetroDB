"""PASS-59-169 — self-updater: checking, download verification, safe
extraction, and the helper's swap / restart / rollback end to end.

No network: GitHub replies are built by hand, and a tiny HTTP server script
stands in for RetroDB answering /health.
"""
import hashlib
import io
import json
import os
import socket
import sqlite3
import stat
import subprocess
import sys
import textwrap
import time
import zipfile
from pathlib import Path

import pytest

import updater_apply
from services import updater

PREFIX = updater.DOWNLOAD_PREFIX


# -----------------------------------------------------------------------------
# Versions, assets, checksums
# -----------------------------------------------------------------------------

def test_versions_compare_as_numbers():
    assert updater.parse_version('v3.10.0') == (3, 10, 0)
    assert updater.parse_version('3.10') is None
    assert updater.is_newer('v3.10.0', '3.9.9')
    assert not updater.is_newer('v3.9.9', '3.10.0')
    assert not updater.is_newer('v3.33.0', '3.33.0')
    assert not updater.is_newer('nightly', '3.33.0')


def _release(tag='v3.40.0', names=(), prefix=PREFIX):
    return {'tag_name': tag, 'assets': [
        {'name': n, 'browser_download_url': f'{prefix}{tag}/{n}', 'size': 10} for n in names]}


def test_source_asset_needs_its_checksum_file():
    names = ['RetroDB-v3.40.0-Linux.zip']
    assert updater.pick_asset(_release(names=names), 'source', 'Linux') is None
    asset = updater.pick_asset(_release(names=names + ['SHA256SUMS.txt']), 'source', 'Linux')
    assert asset['name'] == 'RetroDB-v3.40.0-Linux.zip'
    assert asset['checksum_url'].endswith('/SHA256SUMS.txt')


def test_standalone_prefers_the_full_build_then_cpu():
    cpu = 'RetroDB-v3.40.0-Windows-CPU-Standalone.zip'
    full = 'RetroDB-v3.40.0-Windows-Standalone.zip'
    rel = _release(names=[cpu, cpu + '.sha256'])
    assert updater.pick_asset(rel, 'standalone', 'Windows')['name'] == cpu
    rel = _release(names=[cpu, cpu + '.sha256', full, full + '.sha256'])
    assert updater.pick_asset(rel, 'standalone', 'Windows')['name'] == full
    assert updater.pick_asset(rel, 'standalone', 'Linux') is None


def test_cached_summary_also_picks_its_asset():
    rel = updater._summarise({**_release(names=['RetroDB-v3.40.0-macOS.zip', 'SHA256SUMS.txt']),
                              'html_url': 'https://github.com/milnet01/RetroDB/releases/tag/v3.40.0'})
    assert updater.pick_asset(rel, 'source', 'macOS')['name'] == 'RetroDB-v3.40.0-macOS.zip'


def test_download_urls_must_be_retrodb_releases():
    rel = _release(names=['RetroDB-v3.40.0-Linux.zip', 'SHA256SUMS.txt'],
                   prefix='https://example.com/milnet01/RetroDB/releases/download/')
    assert updater.pick_asset(rel, 'source', 'Linux') is None


def test_checksum_formats():
    h = 'a' * 64
    assert updater.checksum_for(f'{h}  RetroDB-v1.0.0-Linux.zip\n{"b" * 64}  other.zip',
                                'RetroDB-v1.0.0-Linux.zip') == h
    assert updater.checksum_for(f'{h} *RetroDB.zip', 'RetroDB.zip') == h
    assert updater.checksum_for(h.upper(), 'anything.zip') == h
    assert updater.checksum_for(f'{h}  other.zip', 'RetroDB.zip') is None
    assert updater.checksum_for('not a hash  RetroDB.zip', 'RetroDB.zip') is None


def test_install_kind(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, '_base', lambda: str(tmp_path))
    monkeypatch.delenv('LWSM_MANAGED', raising=False)
    assert updater.install_kind() == ('source', None)
    (tmp_path / '.git').mkdir()
    assert updater.install_kind() == (None, 'git')
    monkeypatch.setenv('LWSM_MANAGED', '1')
    assert updater.install_kind() == (None, 'managed')


# -----------------------------------------------------------------------------
# Extraction
# -----------------------------------------------------------------------------

def _zip(path, members):
    """members: name -> (bytes, unix mode or None)."""
    with zipfile.ZipFile(path, 'w') as zf:
        for name, (data, mode) in members.items():
            info = zipfile.ZipInfo(name)
            if mode is not None:
                info.external_attr = mode << 16
            zf.writestr(info, data)
    return path


@pytest.mark.parametrize('name', ['../evil.py', 'RetroDB/../../evil.py', '/etc/evil'])
def test_extract_refuses_paths_that_leave_the_folder(tmp_path, name):
    z = _zip(tmp_path / 'a.zip', {name: (b'x', None)})
    with pytest.raises(updater.UpdateError):
        updater.safe_extract(z, tmp_path / 'out')
    assert not (tmp_path / 'evil.py').exists()


def test_extract_refuses_symlinks(tmp_path):
    z = _zip(tmp_path / 'a.zip', {'RetroDB/link': (b'/etc/passwd', stat.S_IFLNK | 0o777)})
    with pytest.raises(updater.UpdateError):
        updater.safe_extract(z, tmp_path / 'out')


@pytest.mark.skipif(os.name == 'nt', reason='POSIX permission bits')
def test_extract_keeps_executable_bits(tmp_path):
    z = _zip(tmp_path / 'a.zip', {'R/retrodb': (b'#!/bin/sh\n', stat.S_IFREG | 0o755),
                                  'R/notes.txt': (b'hi', stat.S_IFREG | 0o644)})
    updater.safe_extract(z, tmp_path / 'out')
    assert os.stat(tmp_path / 'out/R/retrodb').st_mode & 0o111
    assert not os.stat(tmp_path / 'out/R/notes.txt').st_mode & 0o111


# -----------------------------------------------------------------------------
# Checking and the download job (fake GitHub)
# -----------------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status=200, body=b'', payload=None):
        self.status_code, self.body, self.payload = status, body, payload

    def json(self):
        return self.payload

    def iter_content(self, n):
        for i in range(0, len(self.body), n):
            yield self.body[i:i + n]

    def close(self):
        pass


@pytest.fixture
def sandbox(monkeypatch, tmp_path):
    monkeypatch.setattr(updater, '_base', lambda: str(tmp_path))
    monkeypatch.setattr(updater, '_check_cache', None)
    monkeypatch.delenv('LWSM_MANAGED', raising=False)
    (tmp_path / 'data').mkdir()
    return tmp_path


def test_check_caches_and_skips_drafts(sandbox, monkeypatch):
    calls = []
    payload = {'tag_name': 'v9.0.0', 'draft': False, 'prerelease': False, 'body': 'notes',
               'html_url': 'https://github.com/milnet01/RetroDB/releases/tag/v9.0.0', 'assets': []}
    monkeypatch.setattr(updater, '_http_get', lambda url, **kw: calls.append(url) or FakeResponse(payload=payload))
    first = updater.check()
    assert first['release']['version'] == '9.0.0' and first['release']['notes'] == 'notes'
    updater.check()
    assert len(calls) == 1                       # cached
    payload['prerelease'] = True
    assert updater.check(force=True)['release'] is None


def test_check_records_github_errors(sandbox, monkeypatch):
    monkeypatch.setattr(updater, '_http_get', lambda url, **kw: FakeResponse(status=404))
    result = updater.check(force=True)
    assert result['release'] is None and result['error'] == 'no published release'


def _source_release_zip(tmp_path, version):
    z = tmp_path / f'RetroDB-v{version}-Linux.zip'
    _zip(z, {f'RetroDB-v{version}/app.py': (b'# app', None),
             f'RetroDB-v{version}/updater_apply.py': (b'# helper', None),
             f'RetroDB-v{version}/config.example.py': (f'APP_VERSION = "{version}"\n'.encode(), None)})
    return z.read_bytes()


def _run_job(monkeypatch, sandbox, blob, sums):
    urls = {f'{PREFIX}v9.0.0/RetroDB-v9.0.0-Linux.zip': blob,
            f'{PREFIX}v9.0.0/SHA256SUMS.txt': sums.encode()}
    monkeypatch.setattr(updater, '_http_get', lambda url, **kw: FakeResponse(body=urls[url]))
    monkeypatch.setattr(updater, 'host_platform', lambda: 'Linux')
    job = updater.UpdateJob()
    release = updater._summarise(_release('v9.0.0', ['RetroDB-v9.0.0-Linux.zip', 'SHA256SUMS.txt']))
    assert job.start(release)['success']
    for _ in range(100):
        if job.state != 'downloading':
            break
        time.sleep(0.05)
    return job


def test_download_verifies_and_unpacks(sandbox, monkeypatch, tmp_path):
    blob = _source_release_zip(tmp_path, '9.0.0')
    digest = hashlib.sha256(blob).hexdigest()
    job = _run_job(monkeypatch, sandbox, blob, f'{digest}  RetroDB-v9.0.0-Linux.zip\n')
    assert job.state == 'ready', job.error
    assert os.path.isfile(os.path.join(job.tree, 'app.py'))


def test_download_with_a_wrong_checksum_installs_nothing(sandbox, monkeypatch, tmp_path):
    blob = _source_release_zip(tmp_path, '9.0.0')
    job = _run_job(monkeypatch, sandbox, blob, f'{"0" * 64}  RetroDB-v9.0.0-Linux.zip\n')
    assert job.state == 'error' and 'checksum' in job.error
    assert not os.listdir(sandbox / '.update' / 'staging')
    assert not os.listdir(sandbox / '.update' / 'download')


def test_download_of_another_version_is_refused(sandbox, monkeypatch, tmp_path):
    blob = _source_release_zip(tmp_path, '8.0.0')   # an 8.0.0 tree in the 9.0.0 release
    digest = hashlib.sha256(blob).hexdigest()
    job = _run_job(monkeypatch, sandbox, blob, f'{digest}  RetroDB-v9.0.0-Linux.zip\n')
    assert job.state == 'error'


# -----------------------------------------------------------------------------
# The helper, end to end
# -----------------------------------------------------------------------------

FAKE_APP = textwrap.dedent('''
    import json, os, sys
    from http.server import BaseHTTPRequestHandler, HTTPServer
    here = os.path.dirname(os.path.abspath(__file__))
    version = open(os.path.join(here, 'VERSION')).read().strip()
    if version == 'broken':
        sys.exit(1)

    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({'status': 'alive', 'version': version}).encode()
            self.send_response(200); self.end_headers(); self.wfile.write(body)
        def log_message(self, *a):
            pass

    HTTPServer(('127.0.0.1', int(sys.argv[1])), H).serve_forever()
''')


def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def _dead_pid():
    p = subprocess.Popen([sys.executable, '-c', 'pass'])
    p.wait()
    return p.pid


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    """An installed '1.0.0' with user data, and an unpacked '2.0.0'."""
    install = tmp_path / 'install'
    (install / 'routes').mkdir(parents=True)
    (install / 'data').mkdir()
    (install / 'database').mkdir()
    (install / 'app.py').write_text(FAKE_APP)
    (install / 'VERSION').write_text('1.0.0')
    (install / 'routes' / 'old_only.py').write_text('# dropped in 2.0.0')
    (install / 'config.py').write_text('USER_CONFIG = True')
    (install / 'data' / 'settings.json').write_text('{"mine": true}')
    db = install / 'database' / 'roms.db'
    conn = sqlite3.connect(db)
    conn.execute('CREATE TABLE t (v TEXT)')
    conn.execute("INSERT INTO t VALUES ('before')")
    conn.commit()
    conn.close()
    backup = tmp_path / 'backup.db'
    backup.write_bytes(db.read_bytes())
    updater_apply.write_manifest(str(install), ['app.py', 'VERSION', 'routes/old_only.py'], '1.0.0')

    staging_root = tmp_path / 'staging'
    tree = staging_root / 'RetroDB-v2.0.0'
    (tree / 'routes').mkdir(parents=True)
    (tree / 'app.py').write_text(FAKE_APP)
    (tree / 'VERSION').write_text('2.0.0')
    (tree / 'routes' / 'new_only.py').write_text('# new in 2.0.0')
    (tree / 'config.py').write_text('SHIPPED = True')            # must never land
    (tree / 'config.example.py').write_text('APP_VERSION = "2.0.0"')
    (tree / 'data').mkdir()
    (tree / 'data' / 'settings.json').write_text('{}')          # must never land

    procs = []
    real_spawn = updater_apply.spawn_detached

    def spawn(argv, cwd, log_path, env=None):
        p = real_spawn(argv, cwd, log_path, env)
        procs.append(p)
        return p

    monkeypatch.setattr(updater_apply, 'spawn_detached', spawn)
    monkeypatch.setattr(updater_apply, 'HEALTH_WAIT', 20)
    monkeypatch.setattr(updater_apply, 'EXIT_WAIT', 5)
    port = _free_port()
    plan = {
        'plan_version': 1, 'kind': 'source', 'from_version': '1.0.0', 'to_version': '2.0.0',
        'install_dir': str(install), 'staging_root': str(staging_root), 'staging_dir': str(tree),
        'download_dir': str(tmp_path / 'download'), 'rollback_dir': str(tmp_path / 'rollback'),
        'pid': _dead_pid(), 'port': port,
        'restart_argv': [sys.executable, str(install / 'app.py'), str(port)],
        'restart_cwd': str(install), 'db_path': str(db), 'db_backup': str(backup),
        'status_path': str(install / 'data' / 'update_status.json'),
        'log_path': str(tmp_path / 'update.log'),
    }
    yield install, tree, plan, db
    for p in procs:
        if p.poll() is None:
            p.kill()
            p.wait()


def _status(plan):
    with open(plan['status_path']) as f:
        return json.load(f)


def test_helper_updates_and_keeps_user_data(fake_install):
    install, tree, plan, db = fake_install
    assert updater_apply.apply(plan) == 0
    assert _status(plan)['result'] == 'updated'
    assert updater_apply.healthy_version(plan['port']) == '2.0.0'
    assert (install / 'VERSION').read_text() == '2.0.0'
    assert (install / 'routes' / 'new_only.py').exists()
    assert not (install / 'routes' / 'old_only.py').exists()     # dropped via the manifest
    # config.py follows the new example (it carries APP_VERSION), never the
    # archive's own config.py; the old one is kept for rollback.
    assert (install / 'config.py').read_text() == 'APP_VERSION = "2.0.0"'
    assert (Path(plan['rollback_dir']) / 'config.py').read_text() == 'USER_CONFIG = True'
    assert json.loads((install / 'data' / 'settings.json').read_text()) == {'mine': True}
    assert 'routes/new_only.py' in updater_apply.read_manifest(str(install))


def test_helper_rolls_back_when_the_new_version_does_not_start(fake_install):
    install, tree, plan, db = fake_install
    (tree / 'VERSION').write_text('broken')
    # The "new version" touched the database before it failed.
    conn = sqlite3.connect(db)
    conn.execute("UPDATE t SET v = 'migrated'")
    conn.commit()
    conn.close()
    assert updater_apply.apply(plan) == 1
    status = _status(plan)
    assert status['result'] == 'rolled_back' and 'did not start' in status['reason']
    assert (install / 'VERSION').read_text() == '1.0.0'
    assert (install / 'routes' / 'old_only.py').exists()
    assert not (install / 'routes' / 'new_only.py').exists()
    assert updater_apply.read_manifest(str(install)) == ['app.py', 'VERSION', 'routes/old_only.py']
    assert (install / 'config.py').read_text() == 'USER_CONFIG = True'
    conn = sqlite3.connect(db)
    assert conn.execute('SELECT v FROM t').fetchone()[0] == 'before'
    conn.close()
    assert updater_apply.healthy_version(plan['port']) == '1.0.0'


def test_helper_waits_for_the_old_process(fake_install):
    install, tree, plan, db = fake_install
    sleeper = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])
    try:
        plan['pid'] = sleeper.pid
        updater_apply.EXIT_WAIT = 0.5   # restored by the fixture's monkeypatch
        assert updater_apply.apply(plan) == 1
        assert _status(plan)['result'] == 'failed'
        assert (install / 'VERSION').read_text() == '1.0.0'
    finally:
        sleeper.kill()
        sleeper.wait()


@pytest.mark.parametrize('rel,protected', [
    ('config.py', True), ('database/roms.db', True), ('logs/app.log', True),
    ('data/settings.json', True), ('.update/plan.json', True),
    ('data/changelog.yaml', False), ('static/images/systems/nes.png', False), ('app.py', False),
])
def test_protected_paths(rel, protected):
    assert updater_apply.is_protected(rel) is protected


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

def test_update_routes_are_admin_only(admin_test_client):
    client, csrf = admin_test_client(user={'id': 2, 'username': 'ed', 'role': 'editor'})
    assert client.get('/api/updates/status').status_code == 403
    assert client.post('/api/updates/install', headers={'X-CSRF-Token': csrf}).status_code == 403


def test_status_and_refusals(admin_test_client, sandbox, monkeypatch):
    import config
    monkeypatch.setattr(updater, '_check_cache', {
        'checked_at': time.time(), 'error': None,
        'release': updater._summarise({**_release('v99.0.0', []), 'body': 'x'})})
    client, csrf = admin_test_client()
    st = client.get('/api/updates/status').get_json()
    assert st['current'] == config.APP_VERSION
    assert st['available'] is True and st['can_install'] is False and st['reason'] == 'no_asset'
    r = client.post('/api/updates/install', headers={'X-CSRF-Token': csrf})
    assert r.status_code == 409 and r.get_json()['reason'] == 'not_ready'


def test_helper_standalone_replaces_the_bundle_whole(fake_install):
    install, tree, plan, db = fake_install
    plan['kind'] = 'standalone'
    (install / '_internal').mkdir()
    (install / '_internal' / 'old_lib.so').write_text('old')
    (tree / '_internal').mkdir()
    (tree / '_internal' / 'new_lib.so').write_text('new')
    (install / 'static' / 'images' / 'boxart').mkdir(parents=True)
    (install / 'static' / 'images' / 'boxart' / '1.png').write_text('mine')
    assert updater_apply.apply(plan) == 0
    assert (install / '_internal' / 'new_lib.so').exists()
    assert not (install / '_internal' / 'old_lib.so').exists()
    assert (Path(plan['rollback_dir']) / '_internal' / 'old_lib.so').exists()
    assert (install / 'static' / 'images' / 'boxart' / '1.png').read_text() == 'mine'
    assert (install / 'config.py').read_text() == 'USER_CONFIG = True'
    assert json.loads((install / 'data' / 'settings.json').read_text()) == {'mine': True}


def test_swapped_module_never_runs_its_stale_bytecode(tmp_path):
    """A same-size edit whose staged copy carries the old mtime must not
    load the old .pyc (seen live: config.py 3.33.0 -> 3.33.1 kept 3.33.0)."""
    install, staging = tmp_path / 'install', tmp_path / 'staging'
    install.mkdir()
    staging.mkdir()
    (install / 'mod.py').write_text('V = "1.0.0"\n')
    subprocess.run([sys.executable, '-c', 'import mod'], cwd=install, check=True)
    assert (install / '__pycache__').is_dir()
    old = (install / 'mod.py').stat()
    (staging / 'mod.py').write_text('V = "2.0.0"\n')                  # same size
    os.utime(staging / 'mod.py', ns=(old.st_atime_ns, old.st_mtime_ns))  # same mtime
    swap = updater_apply.Swap(str(install), str(tmp_path / 'rollback'), lambda m: None)
    swap.put('mod.py', str(staging / 'mod.py'))
    updater_apply.purge_bytecode(str(install))
    out = subprocess.run([sys.executable, '-c', 'import mod; print(mod.V)'], cwd=install,
                         check=True, capture_output=True, text=True).stdout.strip()
    assert out == '2.0.0'
