# Pass 44 — Launch route wire-shape and route-existence tests.
import pytest


@pytest.fixture
def app_module(monkeypatch):
    """Return the app module with TESTING=True applied.

    Without TESTING=True the unauthenticated route tests below would
    accept a 5xx (not in the expected set, so they fail "correctly" but
    for the wrong reason — the assertion can't distinguish auth-rejected
    from internal-error). Apply via monkeypatch so the flag is restored
    on teardown (test-audit c-006 MED isolation)."""
    import app as mod
    monkeypatch.setitem(mod.app.config, 'TESTING', True)
    return mod


@pytest.mark.parametrize("path", [
    '/api/game/<int:game_id>/launch',
    '/api/launch/<token>/status',
    '/api/launch/<token>/kill',
    '/api/launches/active',
])
def test_launch_routes_registered(app_module, path):
    """All four launch-subsystem routes must be registered. Collapsed from
    four near-identical single-route tests (test-audit c-006 MED
    parametrisation) — a single failure now surfaces once, and adding a
    new launch route requires only adding to the parametrize list."""
    rules = {r.rule for r in app_module.app.url_map.iter_rules()}
    assert path in rules


def test_unauth_launch_returns_401_or_redirect(app_module):
    """Without a session, POST /api/game/1/launch must be blocked."""
    client = app_module.app.test_client()
    rv = client.post('/api/game/1/launch')
    # login_required short-circuits with a redirect to /login
    assert rv.status_code in (302, 401, 403)


def test_active_endpoint_unauth_blocked(app_module):
    client = app_module.app.test_client()
    rv = client.get('/api/launches/active')
    assert rv.status_code in (302, 401, 403)


def _make_authed_client(app_module, monkeypatch, role, *, user_id=99,
                        username='tester'):
    """Build a Flask test client logged in as `role`, with CSRF seeded.

    Shared by the `player_client` fixture and the standalone
    test_viewer_blocked_403 case (test-audit c-006 MED duplication):
    both setups previously copy-pasted the same triple of monkeypatches
    and CSRF seed. Centralising here means a future stub-shape change
    propagates to one site."""
    monkeypatch.setattr('app.get_current_user',
                        lambda: {'id': user_id, 'username': username, 'role': role})
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    monkeypatch.setattr('app.settings_manager.load_settings',
                        lambda: {'setup_completed': True, 'rom_path': '/tmp'})
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = 'test-csrf-token'
    return client


class TestLaunchEndpointBehavior:
    """Drive the route through monkeypatched resolver + launcher to verify
    response codes for each branch in the request handler."""

    @pytest.fixture
    def player_client(self, app_module, monkeypatch):
        """Player-role client. Bypasses first-time-setup redirect (which
        fires on a fresh checkout where settings.setup_completed is False
        and rom_path is empty)."""
        yield _make_authed_client(app_module, monkeypatch, 'player')

    def _csrf_headers(self):
        return {'X-CSRF-Token': 'test-csrf-token'}

    def _stub_resolver_and_launcher(self, monkeypatch):
        from unittest.mock import MagicMock
        fake_handle = MagicMock(token='tok-1', pid=42, game_id=1, emulator_id=1, started_at=100.0)
        fake_status = MagicMock(state='running', exit_code=None, runtime_s=2.5, stderr_tail='')
        launcher = MagicMock()
        launcher.launch.return_value = fake_handle
        launcher.status.return_value = fake_status
        launcher.kill.return_value = MagicMock(state='exited', exit_code=0, runtime_s=1.0, stderr_tail='')
        launcher.active.return_value = []

        from pathlib import Path
        fake_ctx = MagicMock(
            token='tok-1', argv=['/usr/bin/foo', '/x'],
            game_id=1, emulator_id=1, binary=Path('/usr/bin/foo'),
        )

        monkeypatch.setattr('routes.launch.get_launcher', lambda: launcher)
        monkeypatch.setattr('routes.launch.resolve_launch_context', lambda gid: fake_ctx)
        return launcher

    def test_player_can_launch(self, player_client, monkeypatch):
        launcher = self._stub_resolver_and_launcher(monkeypatch)
        rv = player_client.post('/api/game/1/launch', headers=self._csrf_headers())
        assert rv.status_code == 202
        body = rv.get_json()
        assert body['success'] is True
        assert body['data']['token'] == 'tok-1'

    def test_404_when_resolver_says_game_missing(self, player_client, monkeypatch):
        from services.launcher.base import LaunchResolutionError
        launcher = self._stub_resolver_and_launcher(monkeypatch)

        def _raise(_gid):
            raise LaunchResolutionError('game_id 9999 not found')
        monkeypatch.setattr('routes.launch.resolve_launch_context', _raise)
        rv = player_client.post('/api/game/9999/launch', headers=self._csrf_headers())
        assert rv.status_code == 422

    def test_409_when_same_game_already_running(self, player_client, monkeypatch):
        from unittest.mock import MagicMock
        launcher = self._stub_resolver_and_launcher(monkeypatch)
        existing = MagicMock(token='other', game_id=1, pid=1, emulator_id=1, started_at=0.0)
        launcher.active.return_value = [existing]
        rv = player_client.post('/api/game/1/launch', headers=self._csrf_headers())
        assert rv.status_code == 409
        body = rv.get_json()
        assert body['existing_token'] == 'other'

    def test_viewer_blocked_403(self, app_module, monkeypatch):
        """A viewer cannot launch even though they're logged in."""
        client = _make_authed_client(
            app_module, monkeypatch, 'viewer',
            user_id=1, username='viewer',
        )
        self._stub_resolver_and_launcher(monkeypatch)
        rv = client.post('/api/game/1/launch', headers=self._csrf_headers())
        # has_permission('launch') returns False for viewer; route returns 403
        assert rv.status_code == 403
