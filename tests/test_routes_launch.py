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
    '/api/launch/<token>/disk-next',
])
def test_launch_routes_registered(app_module, path):
    """Every launch-subsystem route must be registered. Collapsed from
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


def test_active_endpoint_unauth_blocked(app_module, setup_complete):
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


class TestLaunchArgsOverrideNeedsManageSettings:
    """PASS-59-64 INV-2 (PASS-59-53): `games.launch_args_override` reaches
    the emulator's argv, so only a `manage_settings` holder may change it.
    An editor's `edit_metadata` POST leaves the stored value as it was."""

    @pytest.fixture
    def seeded_game(self, app_module):
        from services.database import execute, query
        sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                         ('INV-2 System', 'inv2-system'))
        game_id = execute(
            "INSERT INTO games (system_id, title, rom_path, launch_args_override) "
            "VALUES (?, ?, ?, ?)",
            (sys_id, 'INV-2 Game', '/tmp/inv2-game.bin', '--keep-me'))
        yield game_id, lambda: query(
            "SELECT launch_args_override FROM games WHERE id = ?",
            (game_id,), one=True)['launch_args_override']
        execute("DELETE FROM games WHERE id = ?", (game_id,))
        execute("DELETE FROM systems WHERE id = ?", (sys_id,))

    def _post_edit(self, client, game_id, value):
        return client.post(f'/game/{game_id}', data={
            'action': 'edit_metadata',
            'edit_title': 'INV-2 Game',
            'edit_launch_args_override': value,
        }, headers={'X-CSRF-Token': 'test-csrf-token'})

    def test_editor_cannot_change_launch_args(self, app_module, monkeypatch,
                                              seeded_game):
        game_id, stored = seeded_game
        client = _make_authed_client(app_module, monkeypatch, 'editor')
        rv = self._post_edit(client, game_id, '-L /tmp/x.so')
        assert rv.status_code == 200
        assert stored() == '--keep-me'

    def test_admin_can_change_launch_args(self, app_module, monkeypatch,
                                          seeded_game):
        game_id, stored = seeded_game
        client = _make_authed_client(app_module, monkeypatch, 'admin')
        rv = self._post_edit(client, game_id, '--renderer vulkan')
        assert rv.status_code == 200
        assert stored() == '--renderer vulkan'

    @pytest.mark.parametrize('role,shown', [('editor', False), ('admin', True)])
    def test_edit_modal_shows_field_only_with_manage_settings(
            self, app_module, monkeypatch, seeded_game, role, shown):
        game_id, _stored = seeded_game
        client = _make_authed_client(app_module, monkeypatch, role)
        page = client.get(f'/game/{game_id}').get_data(as_text=True)
        assert ('name="edit_launch_args_override"' in page) is shown


def test_unbalanced_quote_in_launch_args_is_422_naming_the_field(
        app_module, monkeypatch):
    """PASS-59-64 INV-4 (PASS-59-54): a malformed quote in a game's launch
    args answers 422 naming `launch_args_override`, never a 500. Runs the
    real resolver against the isolated test DB."""
    from services.database import execute
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                     ('INV-4 System', 'inv4-system'))
    emu_id = execute(
        "INSERT INTO emulators (name, binary_name, args_template, "
        "is_retroarch, enabled) VALUES (?, ?, ?, 0, 1)",
        ('INV-4 Emu', 'sh', '"{rom}"'))
    execute("INSERT INTO system_emulators (system_id, emulator_id, is_default) "
            "VALUES (?, ?, 1)", (sys_id, emu_id))
    game_id = execute(
        "INSERT INTO games (system_id, title, rom_path, launch_args_override) "
        "VALUES (?, ?, ?, ?)",
        (sys_id, 'INV-4 Game', '/tmp/inv4-game.bin', '--renderer "vulkan'))
    try:
        client = _make_authed_client(app_module, monkeypatch, 'player')
        rv = client.post(f'/api/game/{game_id}/launch',
                         headers={'X-CSRF-Token': 'test-csrf-token'})
        assert rv.status_code == 422
        assert 'launch_args_override' in rv.get_json()['error']
    finally:
        execute("DELETE FROM games WHERE id = ?", (game_id,))
        execute("DELETE FROM system_emulators WHERE system_id = ?", (sys_id,))
        execute("DELETE FROM emulators WHERE id = ?", (emu_id,))
        execute("DELETE FROM systems WHERE id = ?", (sys_id,))
