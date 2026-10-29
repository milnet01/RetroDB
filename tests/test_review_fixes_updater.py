"""Regression pins for review findings on the self-updater (PASS-59-169):
cleanup must not wipe a running job's files, any failure must end the job,
the helper must probe the address the server binds (never via a proxy),
a failed refresh must not 500 the download route, and a failed check must
be retried sooner than a successful one.
"""
import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

import updater_apply
from services import updater

PREFIX = updater.DOWNLOAD_PREFIX


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


def _dead_pid():
    p = subprocess.Popen([sys.executable, '-c', 'pass'])
    p.wait()
    return p.pid


def _release(version='9.0.0'):
    names = [f'RetroDB-v{version}-Linux.zip', 'SHA256SUMS.txt']
    return updater._summarise({'tag_name': f'v{version}', 'assets': [
        {'name': n, 'browser_download_url': f'{PREFIX}v{version}/{n}', 'size': 10}
        for n in names]})


# U1 -------------------------------------------------------------------------

@pytest.mark.parametrize('state', ['downloading', 'ready', 'installing'])
def test_old_outcome_file_does_not_wipe_a_live_jobs_files(sandbox, monkeypatch, state):
    p = updater._paths()
    with open(p['status'], 'w') as f:
        json.dump({'result': 'updated', 'helper_pid': _dead_pid()}, f)
    for d in (p['download'], p['staging']):
        os.makedirs(d)
        open(os.path.join(d, 'file'), 'w').close()
    job = updater.UpdateJob()
    job.state = state
    monkeypatch.setattr(updater, 'job', job)
    assert updater.last_result()['result'] == 'updated'
    assert os.path.exists(os.path.join(p['download'], 'file'))
    assert os.path.exists(os.path.join(p['staging'], 'file'))


def test_old_outcome_file_still_cleans_when_no_job_runs(sandbox, monkeypatch):
    p = updater._paths()
    with open(p['status'], 'w') as f:
        json.dump({'result': 'updated', 'helper_pid': _dead_pid()}, f)
    os.makedirs(p['staging'])
    monkeypatch.setattr(updater, 'job', updater.UpdateJob())
    updater.last_result()
    assert not os.path.exists(p['staging'])


# U3 -------------------------------------------------------------------------

@pytest.mark.filterwarnings('ignore::pytest.PytestUnhandledThreadExceptionWarning')
def test_unexpected_download_error_ends_the_job(sandbox, monkeypatch):
    def boom(url, **kw):
        raise RuntimeError('encrypted member')
    monkeypatch.setattr(updater, '_http_get', boom)
    monkeypatch.setattr(updater, 'host_platform', lambda: 'Linux')
    job = updater.UpdateJob()
    assert job.start(_release())['success']
    for _ in range(100):
        if job.state != 'downloading':
            break
        time.sleep(0.02)
    assert job.state == 'error'
    assert 'encrypted member' in job.error


# U5 -------------------------------------------------------------------------

def _serve_health(host, version):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = json.dumps({'status': 'alive', 'version': version}).encode()
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    server = HTTPServer((host, 0), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def test_probe_host_maps_wildcards_to_loopback():
    assert updater_apply.probe_host('0.0.0.0') == '127.0.0.1'
    assert updater_apply.probe_host(None) == '127.0.0.1'
    assert updater_apply.probe_host('localhost') == '127.0.0.1'
    assert updater_apply.probe_host('::') == '::1'
    assert updater_apply.probe_host('192.168.1.20') == '192.168.1.20'


@pytest.mark.skipif(sys.platform != 'linux', reason='127.0.0.2 is loopback on Linux')
def test_health_probe_reaches_a_server_bound_to_one_address():
    server = _serve_health('127.0.0.2', '2.0.0')
    try:
        port = server.server_address[1]
        assert updater_apply.wait_healthy(port, '2.0.0', None, timeout=3, host='127.0.0.2')
    finally:
        server.shutdown()
        server.server_close()


def test_health_probe_ignores_proxy_settings(monkeypatch):
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:9')
    monkeypatch.setenv('HTTP_PROXY', 'http://127.0.0.1:9')
    monkeypatch.delenv('no_proxy', raising=False)
    monkeypatch.delenv('NO_PROXY', raising=False)
    server = _serve_health('127.0.0.1', '2.0.0')
    try:
        assert updater_apply.healthy_version(server.server_address[1]) == '2.0.0'
    finally:
        server.shutdown()
        server.server_close()


def test_plan_carries_the_bind_address_and_apply_uses_it(sandbox, monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, 'SERVER_HOST', '192.168.1.20')
    plan = updater.build_plan(str(tmp_path), 'source', '9.0.0', 5000, None)
    assert plan['host'] == '192.168.1.20'
    assert updater_apply.bind_host(plan) == '192.168.1.20'
    monkeypatch.setenv('RETRODB_HOST', '10.0.0.5')
    assert updater_apply.bind_host({}) == '10.0.0.5'   # a plan from an older version


# U7 -------------------------------------------------------------------------

def test_download_when_refreshed_check_failed_is_not_available(
        admin_test_client, sandbox, monkeypatch):
    monkeypatch.setattr(updater, '_check_cache', {
        'checked_at': time.time(), 'error': None, 'release': _release('99.0.0')})
    monkeypatch.setattr(updater, 'check', lambda force=False: {
        'checked_at': time.time(), 'release': None, 'error': 'GitHub answered 403'})
    client, csrf = admin_test_client()
    r = client.post('/api/updates/download', headers={'X-CSRF-Token': csrf})
    assert r.status_code == 409
    assert r.get_json()['reason'] == 'not_available'


# U8 -------------------------------------------------------------------------

def test_failed_check_is_retried_within_the_hour(sandbox, monkeypatch):
    calls = []
    monkeypatch.setattr(updater, '_http_get',
                        lambda url, **kw: calls.append(url) or FakeResponse(status=500))
    assert updater.check()['error']
    updater._check_cache['checked_at'] = time.time() - 2 * 3600
    updater.check()
    assert len(calls) == 2


def test_successful_check_still_waits_the_full_interval(sandbox, monkeypatch):
    calls = []
    payload = {'tag_name': 'v9.0.0', 'draft': False, 'prerelease': False, 'assets': []}
    monkeypatch.setattr(updater, '_http_get',
                        lambda url, **kw: calls.append(url) or FakeResponse(payload=payload))
    assert updater.check()['release']
    updater._check_cache['checked_at'] = time.time() - 2 * 3600
    updater.check()
    assert len(calls) == 1
