# Pass 44 — Player role + new permissions.
import pathlib

from tests._util import REPO_ROOT

# Local Path wrapper — file uses `/`-operator path arithmetic in 4 places.
_REPO_ROOT = pathlib.Path(REPO_ROOT)


class TestRolePermissions:
    def test_player_role_exists(self):
        from services.auth import ROLE_PERMISSIONS
        assert 'player' in ROLE_PERMISSIONS

    def test_player_can_view_launch_track(self):
        from services.auth import ROLE_PERMISSIONS
        assert ROLE_PERMISSIONS['player'] == {'view', 'launch', 'track_progress'}

    def test_admin_gains_launch_and_track(self):
        from services.auth import ROLE_PERMISSIONS
        assert 'launch' in ROLE_PERMISSIONS['admin']
        assert 'track_progress' in ROLE_PERMISSIONS['admin']

    def test_editor_gains_launch_and_track(self):
        from services.auth import ROLE_PERMISSIONS
        assert 'launch' in ROLE_PERMISSIONS['editor']
        assert 'track_progress' in ROLE_PERMISSIONS['editor']

    def test_viewer_has_view_and_track_progress(self):
        # Pass 45.1 (landed on main while Pass 44 was in PR) widened viewer
        # to include `track_progress` so self-tracking works for every
        # signed-in role, including viewer. Merge of feat/multi-emulator-launch
        # carries that fix forward.
        from services.auth import ROLE_PERMISSIONS
        assert ROLE_PERMISSIONS['viewer'] == {'view', 'track_progress'}


class TestValidRolesConstant:
    def test_valid_roles_includes_player(self):
        from services.auth import VALID_ROLES
        assert 'player' in VALID_ROLES

    def test_valid_roles_matches_role_permissions_keys(self):
        from services.auth import VALID_ROLES, ROLE_PERMISSIONS
        assert set(VALID_ROLES) == set(ROLE_PERMISSIONS.keys())


class TestHasPermission:
    """has_permission already exists; just verify the new perms route correctly."""
    def test_player_has_launch(self, monkeypatch):
        from services import auth
        monkeypatch.setattr(auth, 'g', type('G', (), {'user': {'role': 'player'}})())
        assert auth.has_permission('launch') is True
        assert auth.has_permission('edit') is False

    def test_viewer_lacks_launch(self, monkeypatch):
        from services import auth
        monkeypatch.setattr(auth, 'g', type('G', (), {'user': {'role': 'viewer'}})())
        assert auth.has_permission('launch') is False


class TestRouteAllowlistsUseConstant:
    """The hard-coded ['admin','editor','viewer'] lists in routes/auth.py
    are replaced by VALID_ROLES so adding a role only touches one file."""
    def test_routes_auth_no_hardcoded_role_list(self):
        path = _REPO_ROOT / 'routes' / 'auth.py'
        src = path.read_text()
        assert "['admin', 'editor', 'viewer']" not in src
        assert 'VALID_ROLES' in src


class TestTrackProgressGating:
    """The completion + track-view endpoints must require track_progress."""

    def test_routes_use_permission_decorator(self):
        path = _REPO_ROOT / 'routes' / 'games.py'
        src = path.read_text()
        assert "permission_required('track_progress')" in src or \
               'permission_required("track_progress")' in src
        comp_idx = src.find('def api_update_completion')
        assert comp_idx > 0
        prelude = src[max(0, comp_idx - 500):comp_idx]
        assert 'track_progress' in prelude

        tv_idx = src.find('def api_track_view')
        assert tv_idx > 0
        prelude_tv = src[max(0, tv_idx - 500):tv_idx]
        assert 'track_progress' in prelude_tv
