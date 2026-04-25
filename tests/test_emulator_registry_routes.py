# Pass 44 — emulator registry CRUD route tests.
import pytest


def test_emulator_routes_registered():
    import app as app_module
    rules = {r.rule for r in app_module.app.url_map.iter_rules()}
    assert '/api/emulators' in rules
    assert '/api/emulators/<int:emulator_id>' in rules
    assert '/api/system_emulators' in rules
    assert '/api/emulators/for-system/<int:system_id>' in rules


def test_mutating_routes_require_admin():
    """POST/PUT/DELETE handlers should be admin-only."""
    src = open('routes/emulators.py').read()
    # Each mutating handler must be decorated with @admin_required
    # (or @permission_required('manage_settings')).
    assert '@admin_required' in src or "permission_required('manage_settings')" in src


def test_unauth_list_blocked():
    import app as app_module
    client = app_module.app.test_client()
    rv = client.get('/api/emulators')
    # login_required short-circuits — redirect to /login
    assert rv.status_code in (302, 401, 403)


class TestEmulatorCRUD:
    @pytest.fixture
    def admin_client(self, monkeypatch):
        import app as app_module
        monkeypatch.setattr('app.get_current_user',
                            lambda: {'id': 1, 'username': 'admin', 'role': 'admin'})
        monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['_csrf_token'] = 'tok'
        return client

    def _csrf(self):
        return {'X-CSRF-Token': 'tok'}

    def test_admin_can_list(self, admin_client, monkeypatch):
        monkeypatch.setattr('routes.emulators.query',
                            lambda *a, **kw: [{'id': 1, 'name': 'RetroArch'}])
        rv = admin_client.get('/api/emulators')
        assert rv.status_code == 200
        body = rv.get_json()
        assert body['success'] is True

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

    def test_viewer_cannot_create(self, monkeypatch):
        import app as app_module
        monkeypatch.setattr('app.get_current_user',
                            lambda: {'id': 1, 'username': 'v', 'role': 'viewer'})
        monkeypatch.setattr('app.get_user_settings', lambda _uid: {})
        client = app_module.app.test_client()
        with client.session_transaction() as sess:
            sess['_csrf_token'] = 'tok'
        rv = client.post('/api/emulators',
                         json={'name': 'X', 'binary_name': 'x', 'args_template': '{rom}'},
                         headers={'X-CSRF-Token': 'tok'})
        # admin_required redirects non-admins
        assert rv.status_code in (302, 403)
