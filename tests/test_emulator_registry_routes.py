# Pass 44 — emulator registry CRUD route tests.
import pytest


# Module-level sentinels: hardcoded test values, kept in one place so the
# token literal in the session and the X-CSRF-Token header can't drift, and
# so the rom_path stub is clearly a fake (won't accidentally pass any
# real-directory existence check the route might grow).
_CSRF_TOKEN = 'tok'
_FAKE_ROM_PATH = '/nonexistent/rom-path-stub'


def _make_client(monkeypatch, role):
    """Build a Flask test client logged in as the given role.

    Shared by `admin_client` and `viewer_client` fixtures — both tests need
    identical session + monkeypatch wiring, only the role string differs.
    The source-grep `test_mutating_routes_require_admin` check was removed
    in favour of the HTTP-level viewer-blocked tests below: a source grep
    for `@admin_required` passes if the decorator appears anywhere in the
    file, even on a read-only route, so it provided false confidence.
    """
    import app as app_module
    monkeypatch.setattr('app.get_current_user',
                        lambda: {'id': 1, 'username': role, 'role': role})
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    monkeypatch.setattr('app.settings_manager.load_settings',
                        lambda: {'setup_completed': True, 'rom_path': _FAKE_ROM_PATH})
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess['_csrf_token'] = _CSRF_TOKEN
    return client


def test_emulator_routes_registered():
    import app as app_module
    rules = {r.rule for r in app_module.app.url_map.iter_rules()}
    assert '/api/emulators' in rules
    assert '/api/emulators/<int:emulator_id>' in rules
    assert '/api/system_emulators' in rules
    assert '/api/emulators/for-system/<int:system_id>' in rules


def test_unauth_list_blocked(monkeypatch, setup_complete):
    import app as app_module
    # TESTING=True so the test client doesn't swallow exceptions silently
    # (test-audit c-002 MED isolation): without it a 500 from internal
    # error would NOT match `in (302, 401, 403)` but the test author's
    # intent — exercise the auth redirect — would be invisible.
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    client = app_module.app.test_client()
    rv = client.get('/api/emulators')
    # login_required short-circuits — redirect to /login
    assert rv.status_code in (302, 401, 403)


class TestEmulatorCRUD:
    @pytest.fixture
    def admin_client(self, monkeypatch):
        return _make_client(monkeypatch, 'admin')

    @pytest.fixture
    def viewer_client(self, monkeypatch):
        return _make_client(monkeypatch, 'viewer')

    def _csrf(self):
        return {'X-CSRF-Token': _CSRF_TOKEN}

    def test_admin_can_list(self, admin_client, monkeypatch):
        monkeypatch.setattr('routes.emulators.query',
                            lambda *a, **kw: [{'id': 1, 'name': 'RetroArch'}])
        rv = admin_client.get('/api/emulators')
        assert rv.status_code == 200
        body = rv.get_json()
        assert body['success'] is True

    def test_player_listed_only_once_found(self, admin_client, monkeypatch, tmp_path):
        """The bundled player's row stays out of the list until its program
        is found (user, 2026-10-22)."""
        rows = [{'id': 1, 'name': 'RetroArch', 'is_player': 0},
                {'id': 2, 'name': 'RetroDB Player', 'is_player': 1, 'is_retroarch': 0,
                 'binary_name': 'retrodb-player-not-installed', 'binary_path_override': None}]
        monkeypatch.setattr('routes.emulators.query', lambda *a, **kw: rows)
        names = [e['name'] for e in admin_client.get('/api/emulators').get_json()['emulators']]
        assert names == ['RetroArch']

        binary = tmp_path / 'retrodb-player'
        binary.write_text('#!/bin/sh\n')
        binary.chmod(0o755)
        rows[1]['binary_path_override'] = str(binary)
        names = [e['name'] for e in admin_client.get('/api/emulators').get_json()['emulators']]
        assert names == ['RetroArch', 'RetroDB Player']

    def test_admin_can_create(self, admin_client, monkeypatch):
        captured = {}

        def _execute(sql, args=()):
            captured['sql'] = sql
            captured['args'] = args
            return 42  # new id

        monkeypatch.setattr('routes.emulators.execute', _execute)
        rv = admin_client.post('/api/emulators',
                               json={'name': 'X', 'binary_name': 'x', 'args_template': '{rom}'},
                               headers=self._csrf())
        assert rv.status_code == 201
        assert rv.get_json()['id'] == 42

    def test_create_validates_required_fields(self, admin_client, monkeypatch):
        monkeypatch.setattr('routes.emulators.execute', lambda *a, **kw: 1)
        rv = admin_client.post('/api/emulators', json={'name': 'X'},
                               headers=self._csrf())
        assert rv.status_code == 400

    def test_admin_can_update(self, admin_client, monkeypatch):
        captured = {}

        def _execute(sql, args=()):
            captured['sql'] = sql
            captured['args'] = args
            return 1

        monkeypatch.setattr('routes.emulators.execute', _execute)
        rv = admin_client.put('/api/emulators/5',
                              json={'binary_path_override': '/opt/foo.AppImage'},
                              headers=self._csrf())
        assert rv.status_code == 200
        # The UPDATE should set binary_path_override to the supplied path.
        assert 'binary_path_override' in captured['sql']
        # `in` on a list/tuple checks element equality — pin the value
        # explicitly (without indexing, which would over-pin SQL param
        # order). This is enough to catch a regression that drops or
        # silently rewrites the path arg, while leaving the SQL param
        # order free to vary (test-audit c-002 MED assertions).
        assert '/opt/foo.AppImage' in tuple(captured['args']), (
            f"expected '/opt/foo.AppImage' as a positional arg, "
            f"got args={captured['args']!r}"
        )

    def test_admin_can_delete(self, admin_client, monkeypatch):
        captured = {}

        def _execute(sql, args=()):
            captured['sql'] = sql
            captured['args'] = args
            return 1

        monkeypatch.setattr('routes.emulators.execute', _execute)
        rv = admin_client.delete('/api/emulators/7', headers=self._csrf())
        assert rv.status_code == 200
        assert 'DELETE FROM emulators' in captured['sql']
        assert 7 in captured['args']

    def test_viewer_cannot_create(self, viewer_client):
        rv = viewer_client.post('/api/emulators',
                                json={'name': 'X', 'binary_name': 'x', 'args_template': '{rom}'},
                                headers=self._csrf())
        # admin_required redirects non-admins
        assert rv.status_code in (302, 403)

    def test_viewer_cannot_delete(self, viewer_client):
        rv = viewer_client.delete('/api/emulators/7', headers=self._csrf())
        # admin_required redirects non-admins
        assert rv.status_code in (302, 403)


# PASS-59-91 INV-6 — GET /api/system_emulators is admin-only and returns each
# mapping with `resolves` and `bios`.
PROBE = 'MapListProbe'


@pytest.fixture
def mapping(setup_complete):
    from services.database import execute
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                     (f'{PROBE} Sys', 'maplistprobe'))
    emu_id = execute(
        "INSERT INTO emulators (name, binary_name, args_template, is_retroarch, enabled) "
        "VALUES (?, 'maplistprobe-not-installed', '\"{rom}\"', 0, 1)", (f'{PROBE} Emu',))
    map_id = execute("INSERT INTO system_emulators (system_id, emulator_id, is_default) "
                     "VALUES (?, ?, 1)", (sys_id, emu_id))
    yield map_id
    execute("DELETE FROM system_emulators WHERE id = ?", (map_id,))
    execute("DELETE FROM emulators WHERE id = ?", (emu_id,))
    execute("DELETE FROM systems WHERE id = ?", (sys_id,))


def _role_client(monkeypatch, role):
    import app as app_module
    monkeypatch.setitem(app_module.app.config, 'TESTING', True)
    monkeypatch.setattr('app.get_current_user',
                        lambda: {'id': 99, 'username': 'tester', 'role': role})
    monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
    return app_module.app.test_client()


def test_admin_lists_mappings_with_resolves_and_bios(monkeypatch, mapping):
    rv = _role_client(monkeypatch, 'admin').get('/api/system_emulators')
    assert rv.status_code == 200, rv.data
    row = next(m for m in rv.get_json()['mappings'] if m['id'] == mapping)
    assert row['emulator_name'] == f'{PROBE} Emu'
    assert row['system_name'] == f'{PROBE} Sys'
    assert row['resolves'] is False
    assert row['bios']['state'] == 'unknown'


def test_viewer_cannot_list_mappings(monkeypatch, mapping):
    assert _role_client(monkeypatch, 'viewer').get('/api/system_emulators').status_code == 403
