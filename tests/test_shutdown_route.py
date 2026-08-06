"""Contract tests for POST /api/shutdown (one-click-launch feature, v3.21.0).

Pass 57.7 item 7 replaced this file's `inspect.getsource` string-matching with
HTTP-level tests. A source grep for `signal.SIGTERM` passes if the literal
appears anywhere in the function — in a docstring, in dead code, on a branch
that never runs — so it proved the text was present, not that the route
behaves. (The same swap was made in test_emulator_registry_routes.py, for the
same reason.)

The shutdown body cannot simply be driven: it sends SIGTERM to the test
runner's own pid. Monkeypatching `os.kill` is NOT enough on its own, because
the patch is undone at teardown and the route's real thread sleeps a second
first — a thread that had not fired yet would then send a *real* SIGTERM and
kill pytest. So `threading.Thread` is stubbed to capture the callable instead
of running it, and the body is invoked synchronously under a patched os.kill.
"""
import os
import signal

import pytest

_CSRF_TOKEN = 'tok'


def _make_client(monkeypatch, role):
    """Flask test client logged in as `role` (mirrors the shared pattern in
    tests/test_emulator_registry_routes.py::_make_client)."""
    import app as app_module

    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    monkeypatch.setattr('app.get_current_user',
                        lambda: {'id': 1, 'username': role, 'role': role})
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    monkeypatch.setattr('app.settings_manager.load_settings',
                        lambda: {'setup_completed': True})
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = _CSRF_TOKEN
    return client


@pytest.fixture
def armed_threads(monkeypatch):
    """Stub `threading.Thread` in routes.maintenance; return the capture list.

    Each entry exposes `.target`, `.daemon` and `.started` without ever
    running the callable — see the module docstring for why the real thread
    must not be allowed to fire.
    """
    import routes.maintenance as maint

    captured = []

    class _CapturedThread:
        def __init__(self, target=None, daemon=None, **kwargs):
            self.target = target
            self.daemon = daemon
            self.started = False
            captured.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(maint.threading, 'Thread', _CapturedThread)
    return captured


@pytest.fixture
def admin_client(monkeypatch):
    return _make_client(monkeypatch, 'admin')


@pytest.fixture
def viewer_client(monkeypatch):
    return _make_client(monkeypatch, 'viewer')


def _csrf():
    return {'X-CSRF-Token': _CSRF_TOKEN}


def test_shutdown_route_registered():
    """The route exists at the rule the Server Controls button POSTs to."""
    import app as app_module

    rules = {r.endpoint: (r.rule, r.methods)
             for r in app_module.app.url_map.iter_rules()}
    assert 'maintenance.api_shutdown' in rules, 'shutdown route not registered'
    rule, methods = rules['maintenance.api_shutdown']
    assert rule == '/api/shutdown'
    assert 'POST' in methods
    assert 'GET' not in methods, 'shutdown must not be reachable by GET'


def test_unauthenticated_post_is_rejected(app_client, armed_threads):
    resp = app_client.post('/api/shutdown', follow_redirects=False)
    assert resp.status_code in (301, 302, 303, 400, 401, 403), \
        f'unauthenticated shutdown should be rejected, got {resp.status_code}'
    assert armed_threads == [], 'no shutdown must be armed for an anonymous caller'


def test_viewer_cannot_shut_the_server_down(viewer_client, armed_threads):
    """admin_required, not login_required — a logged-in viewer is still barred,
    and crucially arms nothing on the way out."""
    resp = viewer_client.post('/api/shutdown', headers=_csrf(),
                              follow_redirects=False)
    assert resp.status_code in (301, 302, 303, 400, 401, 403), \
        f'viewer shutdown should be rejected, got {resp.status_code}'
    assert armed_threads == [], 'a non-admin must not arm the shutdown'


def test_admin_arms_a_started_daemon_thread(admin_client, armed_threads):
    resp = admin_client.post('/api/shutdown', headers=_csrf())
    assert resp.status_code == 200, resp.get_data(as_text=True)
    assert resp.get_json()['success'] is True

    assert len(armed_threads) == 1, 'expected exactly one shutdown thread'
    thread = armed_threads[0]
    assert thread.started, 'the shutdown thread must actually be started'
    assert thread.daemon is True, \
        'a non-daemon thread would keep the interpreter alive past the drain'


def test_shutdown_body_sigterms_its_own_pid(admin_client, armed_threads,
                                            monkeypatch):
    """SIGTERM to our own pid — not sys.exit, not os._exit.

    app.py installs the graceful-drain handler on SIGTERM. sys.exit would only
    unwind this worker thread while waitress kept serving; os._exit would skip
    the job drain the handler exists to provide. Either substitution leaves
    `calls` empty and reddens this test.

    The body's ~1 s response-flush sleep runs for real: `time.sleep` is shared
    with the app's background job threads, so no-op'ing it globally would spin
    them hot for the duration.
    """
    admin_client.post('/api/shutdown', headers=_csrf())
    body = armed_threads[0].target

    calls = []
    monkeypatch.setattr(os, 'kill', lambda pid, sig: calls.append((pid, sig)))
    body()

    assert calls == [(os.getpid(), signal.SIGTERM)], \
        f'expected one SIGTERM to our own pid, got {calls}'
