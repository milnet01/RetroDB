# =============================================================================
# Pass 45 — indie-review 2026-04-25 fold-in
# =============================================================================
# Regression pins for findings folded as Pass 45 sub-passes. Tests are
# behaviour-anchored where possible (Pass 45.18 flags the source-grep
# antipattern); only configuration assertions go through grep.
# =============================================================================

import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# -----------------------------------------------------------------------------
# 45.1 — track_progress permission unsatisfiable
# -----------------------------------------------------------------------------
class TestPass45_1TrackProgressPermission:
    """Pass 41.9.A added @permission_required('track_progress') to
    api_track_view + api_update_completion but never granted the permission
    to any role. has_permission('track_progress') therefore returned False
    for every user including admin → both endpoints redirected to /dashboard
    and the completion-toggle / recently-viewed features were dead in
    production. Pass 45.1 grants the permission to admin/editor/viewer and
    teaches permission_required to return a 403 JSON envelope on /api/*
    routes (instead of a 302 to /dashboard, which a fetch() caller can't
    follow meaningfully)."""

    def test_admin_role_grants_track_progress(self):
        from services.auth import ROLE_PERMISSIONS
        assert 'track_progress' in ROLE_PERMISSIONS['admin']

    def test_editor_role_grants_track_progress(self):
        from services.auth import ROLE_PERMISSIONS
        assert 'track_progress' in ROLE_PERMISSIONS['editor']

    def test_viewer_role_grants_track_progress(self):
        """Viewer is the role most likely to be a casual Player — the
        whole point of Pass 41.9 was to let non-editors track their own
        progress without granting them edit/scrape rights."""
        from services.auth import ROLE_PERMISSIONS
        assert 'track_progress' in ROLE_PERMISSIONS['viewer']

    def test_permission_denied_on_api_returns_403_json(self):
        """A logged-in user who lacks the permission must receive a 403
        with the canonical JSON envelope on /api/* — not a 302 to /dashboard
        (which fetch() with credentials follows transparently and turns the
        error into a confusing dashboard-HTML response)."""
        import app as app_module
        from services import auth as auth_mod

        # Stash the permission map, drop track_progress so the decorator
        # denies access, then restore on teardown.
        original = auth_mod.ROLE_PERMISSIONS['admin'].copy()
        auth_mod.ROLE_PERMISSIONS['admin'] = original - {'track_progress'}
        try:
            app_module.app.config['TESTING'] = True
            with app_module.app.test_client() as c:
                # Pretend the request came from an authenticated admin so
                # the decorator runs the permission check, not the login
                # redirect.  We monkey-patch get_current_user since the
                # session-cookie path needs a seeded users row.
                _stub_authenticated_admin(app_module)
                resp = c.post(
                    '/api/game/1/completion',
                    json={'status': 'played'},
                    follow_redirects=False,
                )
        finally:
            auth_mod.ROLE_PERMISSIONS['admin'] = original
            _unstub_authenticated_admin(app_module)

        assert resp.status_code == 403, (
            f"Expected 403 on permission denied, got {resp.status_code} "
            f"with Location={resp.headers.get('Location', '')}"
        )
        body = resp.get_json()
        assert body is not None, "Response must be JSON, not HTML redirect"
        assert body.get('success') is False
        assert 'error' in body

    def test_permission_denied_on_page_route_still_redirects(self):
        """Non-/api/* routes keep the existing redirect-to-dashboard
        behaviour so a user clicking a UI link gets a sensible flashed
        error rather than a raw 403 page."""
        import services.auth as auth_mod
        from inspect import getsource
        body = getsource(auth_mod.permission_required)
        # Both branches must exist.  We grep here because the routing
        # tables don't expose any non-/api/* permission_required usage
        # in this repo (the smoke wouldn't exercise the branch).
        assert "redirect(url_for('dashboard'))" in body
        assert "/api/" in body


# -----------------------------------------------------------------------------
# 45.19 — release.yml heredoc indentation
# -----------------------------------------------------------------------------
class TestPass45_19ReleaseHeredoc:
    """Two `python - <<'PY'` blocks in .github/workflows/release.yml had their
    Python source indented 10 spaces (the YAML baseline).  Bash heredocs
    without `-` preserve the indent and pass it to Python verbatim, which
    then raises `IndentationError: unexpected indent` on the very first
    statement.  Net effect: both the build-ZIPs and the extract-changelog
    steps fail before they execute, so every tag-driven release has been
    broken since the workflow landed.  Pass 45.19 routes the Python through
    a YAML env-var (literal block scalar) and runs `python -c "$SCRIPT"` —
    the env-var expansion strips the YAML indent before Python sees it."""

    def test_no_indented_heredoc_python_in_release_yml(self):
        """The bug shape was `python - <<'PY'` followed by indented Python.
        After the fix, no `<<'PY'` heredoc should remain because both have
        been migrated to env-var + `python -c`."""
        path = os.path.join(_REPO_ROOT, '.github', 'workflows', 'release.yml')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        assert "<<'PY'" not in body, (
            "release.yml must not use indented `<<'PY'` heredocs — Python "
            "rejects the YAML-baseline indent (Pass 45.19)"
        )
        assert "<< 'PY'" not in body, (
            "release.yml must not use indented `<<'PY'` heredocs (Pass 45.19)"
        )

    def test_release_yml_executes_python_via_env_var_or_file(self):
        """The replacement pattern is either `python -c "$ENV_VAR"` (env-var
        block scalar strips indent) or `python .github/scripts/foo.py`
        (out-of-band script file).  At least one must be present for each
        Python step that previously used a heredoc."""
        path = os.path.join(_REPO_ROOT, '.github', 'workflows', 'release.yml')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        # Build step + changelog step both moved to env-var pattern.
        assert 'python -c "$' in body or '.github/scripts/' in body, (
            "release.yml must run Python via env-var or script file "
            "(Pass 45.19)"
        )


def _stub_authenticated_admin(app_module):
    """Replace before_request user loader with a fake admin so the
    decorator's ``g.user`` lookup succeeds during the test.  We splice
    the stub onto ``g`` directly via a request-local hook."""
    from flask import g
    import services.auth as auth_mod

    fake = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}

    def _before():
        g.user = fake

    # Register only once; idempotent across parametrise runs.
    funcs = app_module.app.before_request_funcs.setdefault(None, [])
    if _before not in funcs:
        funcs.insert(0, _before)
    app_module._pass45_test_before = _before


def _unstub_authenticated_admin(app_module):
    fn = getattr(app_module, '_pass45_test_before', None)
    if fn is None:
        return
    funcs = app_module.app.before_request_funcs.get(None, [])
    if fn in funcs:
        funcs.remove(fn)
    delattr(app_module, '_pass45_test_before')
