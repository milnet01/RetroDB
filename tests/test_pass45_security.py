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


# -----------------------------------------------------------------------------
# 45.3 — AI Fill breaks fill-only invariant on integer columns
# -----------------------------------------------------------------------------
class TestPass45_3AiFillIntFields:
    """routes/games_ai.py:109 wrote bare `players = ?` so an AI response of
    `"0"` (which Gemini/Claude often return when the model doesn't know the
    answer) clobbered a curated `players=4` to 0.  The same bug fires for
    the score/count int fields whenever current is NULL — a spurious 0 gets
    written and the row is marked as 'AI-filled' in scrape_history.

    The CLAUDE.md scraper-fill-only invariant is supposed to apply to AI
    Fill too: an empty/unknown response must preserve the existing value.
    Pass 45.3 skips the write when an int field coerces to 0."""

    @staticmethod
    def _capture_updates(monkeypatch, *, ai_data, game_row):
        """Drive routes.games_ai.api_game_ai_fill end-to-end with stubbed I/O
        and return the (sql, values) tuple passed to ``execute``."""
        import importlib

        import app as app_module
        import routes.games_ai as ga
        import scraper.scrape_ai as scrape_ai
        import scraper.hybrid_scraper as hybrid

        captured = {}

        def fake_query(sql, params=(), one=False):
            if 'FROM games g' in sql or 'FROM games\n' in sql or 'FROM games ' in sql:
                return game_row if one else [game_row]
            return None if one else []

        def fake_execute(sql, params=()):
            if sql.startswith('UPDATE games SET'):
                captured['sql'] = sql
                captured['values'] = params
            return None

        monkeypatch.setattr(ga, 'query', fake_query)
        monkeypatch.setattr(ga, 'execute', fake_execute)
        monkeypatch.setattr(ga, 'invalidate_analytics_cache', lambda: None)
        monkeypatch.setattr(ga, 'cross_map_ratings', lambda d: d)
        monkeypatch.setattr(ga, 'infer_rating_from_content', lambda _d: None)
        monkeypatch.setattr(ga, 'generate_sort_title', lambda _t: '')
        monkeypatch.setattr(scrape_ai, 'get_game_details',
                            lambda *_a, **_kw: ai_data)
        monkeypatch.setattr(hybrid, 'should_use_default_controller',
                            lambda _v: False)
        monkeypatch.setattr(hybrid, 'get_system_default_controller_name',
                            lambda _sid: None)

        # app.before_request runs `get_current_user()` and writes the result
        # to `g.user`; bypass the DB lookup with a fake admin so editor_required
        # admits the POST.
        fake_admin = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}
        monkeypatch.setattr(app_module, 'get_current_user',
                            lambda: fake_admin)
        monkeypatch.setattr(app_module, 'get_user_settings',
                            lambda _uid: None)

        app_module.app.config['TESTING'] = True
        with app_module.app.test_client() as c:
            with c.session_transaction() as sess:
                sess['_csrf_token'] = 'test-csrf-token-pass45_3'
            resp = c.post(
                '/api/game/1/ai-fill',
                headers={'X-CSRF-Token': 'test-csrf-token-pass45_3'},
            )

        assert resp.status_code == 200, (
            f"Route returned {resp.status_code}: {resp.get_data(as_text=True)[:300]}"
        )
        return captured

    def _row(self, **overrides):
        """Minimal game row covering every column the route reads."""
        base = {
            'id': 1, 'title': 'Test Game', 'system_id': 1,
            'system_name': 'PS3', 'system_folder': 'ps3',
            'genre': 'Action', 'description': 'desc', 'developer': 'Dev',
            'publisher': 'Pub', 'release_date': '2010-01-01',
            'players': 4, 'modes': 'Single-player',
            'esrb_rating': 'M', 'pegi_rating': '18',
            'cero_rating': '', 'usk_rating': '', 'acb_rating': '',
            'fpb_rating': '', 'grac_rating': '', 'classind_rating': '',
            'region': 'NTSC-U', 'franchise': '', 'similar_games': '',
            'controller_support': 'Gamepad', 'save_type': 'Cloud',
            'game_structure': 'Linear', 'perspective': 'Third-Person',
            'dimension': '3D', 'campaign': 'Story',
            'other_platforms': '', 'edition': 'Standard Edition',
            'critic_score': 85, 'critic_score_count': 50,
            'user_score': 8.5, 'user_score_count': 100,
            'scrape_history': None,
        }
        base.update(overrides)
        return base

    def test_ai_zero_does_not_overwrite_curated_players(self, monkeypatch):
        """Curated players=4, AI returns players='0'.  Pre-fix: UPDATE wrote
        players=0.  Post-fix: no players clause is emitted."""
        captured = self._capture_updates(
            monkeypatch,
            ai_data={'players': '0'},
            game_row=self._row(players=4),
        )
        sql = captured.get('sql', '')
        # Either no UPDATE at all (filled_fields empty), or an UPDATE that
        # does not touch players.
        assert 'players = ?' not in sql, (
            f"AI '0' must not generate a `players = ?` clause "
            f"(scraper-fill-only invariant). Got SQL: {sql!r}"
        )

    def test_ai_zero_does_not_write_spurious_critic_score(self, monkeypatch):
        """Curated critic_score=NULL, AI returns critic_score='0'.  Pre-fix:
        a `critic_score = 0` clause was emitted (an unknown score persisted
        as a real 0/100).  Post-fix: skipped."""
        captured = self._capture_updates(
            monkeypatch,
            ai_data={'critic_score': '0'},
            game_row=self._row(critic_score=None),
        )
        sql = captured.get('sql', '')
        assert 'critic_score = ?' not in sql, (
            f"AI '0' must not write a spurious zero score. Got SQL: {sql!r}"
        )

    def test_ai_nonzero_int_still_applies(self, monkeypatch):
        """Sanity check: a real int from AI still flows through.  Curated
        players=NULL, AI returns players='2' → UPDATE writes players=2."""
        captured = self._capture_updates(
            monkeypatch,
            ai_data={'players': '2'},
            game_row=self._row(players=None),
        )
        sql = captured.get('sql', '')
        values = captured.get('values', ())
        assert 'players = ?' in sql, (
            f"Non-zero AI int must still apply. Got SQL: {sql!r}"
        )
        assert 2 in values, (
            f"Expected players=2 in update values, got {values!r}"
        )

    def test_ai_invalid_int_string_skipped(self, monkeypatch):
        """Curated players=4, AI returns players='unknown' (un-parseable).
        The except-clause already skipped this; pin it in regression."""
        captured = self._capture_updates(
            monkeypatch,
            ai_data={'players': 'unknown'},
            game_row=self._row(players=4),
        )
        sql = captured.get('sql', '')
        assert 'players = ?' not in sql, (
            f"Un-parseable AI int must be skipped. Got SQL: {sql!r}"
        )


# -----------------------------------------------------------------------------
# 45.2 — DNS-rebinding TOCTOU on every scraper download path
# -----------------------------------------------------------------------------
class TestPass45_2DnsRebindingPin:
    """Pass 32.7 introduced ``services.ssrf.pin_host_ip`` but only
    ``routes/museum.py`` actually wrapped its GETs in it. Every other
    scraper download path called ``validate_outbound_url`` then issued a
    bare GET — between those two calls a hostile DNS record could flip
    from a public A-record to 127.0.0.1, defeating the SSRF gate. Pass
    45.2 introduces ``validate_and_pin_url`` and threads ``pin_host_ip``
    through ``base_scraper.download_image``, ``metadata_merger._download_
    and_finalize`` / ``_download_ss_media``, ``scrape_screenscraper.
    download_media``, and ``services.image_utils._download_model``.

    These tests pin the contract by stubbing the redirect-chain validator
    and the outbound HTTP call, then checking that ``socket.getaddrinfo``
    inside the GET resolves through the per-thread pin (i.e. returns the
    pinned IP) rather than falling through to real DNS. We never let the
    test fire a real network request.
    """

    @staticmethod
    def _capture_pin_during_get():
        """Build a fake response + a getter that records the pinned IP
        observed at GET time. Returns (fake_get, observed)."""
        import socket
        from contextlib import contextmanager

        observed = {}

        class _FakeResp:
            status_code = 200
            headers = {'Content-Length': '5', 'Content-Type': 'image/png'}

            def iter_content(self, chunk_size=8192):
                yield b'PNG\x89\x00'

            def raise_for_status(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        @contextmanager
        def fake_get(url, *args, **kwargs):
            # At GET time, record what getaddrinfo returns for the host
            # named in the URL — this is the moment that pin_host_ip()
            # has to be active for DNS-rebinding to be defeated.
            from urllib.parse import urlparse
            host = urlparse(url).hostname
            try:
                infos = socket.getaddrinfo(host, None)
                observed['ips'] = [info[4][0] for info in infos]
            except Exception as e:
                observed['error'] = repr(e)
            yield _FakeResp()

        return fake_get, observed

    def _patch_validators(self, monkeypatch, pinned_ip='203.0.113.42'):
        """Patch validate_redirect_chain + validate_outbound_url so the
        helpers think every URL is safe and the pinned IP is `pinned_ip`."""
        import services.ssrf as ssrf

        def _fake_chain(session, url, *, max_redirects=3, timeout=5):
            return url, None

        def _fake_validate(url, *, require_https=False):
            return True, url, [pinned_ip]

        monkeypatch.setattr(ssrf, 'validate_redirect_chain', _fake_chain)
        monkeypatch.setattr(ssrf, 'validate_outbound_url', _fake_validate)
        return pinned_ip

    def test_validate_and_pin_url_returns_resolved_ip(self, monkeypatch):
        """The new helper must surface the IP captured from the final-URL
        re-resolution so the caller has something to pass to pin_host_ip."""
        ip = self._patch_validators(monkeypatch, pinned_ip='198.51.100.7')
        from services.ssrf import validate_and_pin_url
        safe_url, pinned_ip, err = validate_and_pin_url(
            object(), 'https://example.com/x', max_redirects=3, timeout=5,
        )
        assert err is None
        assert safe_url == 'https://example.com/x'
        assert pinned_ip == ip

    def test_validate_and_pin_url_propagates_chain_error(self, monkeypatch):
        """A redirect-chain rejection must come back as the third tuple
        element so callers can log/abort without a second probe."""
        import services.ssrf as ssrf

        monkeypatch.setattr(ssrf, 'validate_redirect_chain',
                            lambda *a, **kw: (None, 'too many redirects'))
        from services.ssrf import validate_and_pin_url
        safe_url, pinned_ip, err = validate_and_pin_url(
            object(), 'https://example.com/x',
        )
        assert safe_url is None
        assert pinned_ip is None
        assert err == 'too many redirects'

    def test_base_scraper_download_image_pins_ip_for_get(self, tmp_path, monkeypatch):
        """The scraper image-download path must hold a pin_host_ip context
        for the duration of the GET — so getaddrinfo inside the GET resolves
        to the pinned IP, not whatever DNS currently says."""
        ip = self._patch_validators(monkeypatch, pinned_ip='203.0.113.55')
        fake_get, observed = self._capture_pin_during_get()

        from scraper import base_scraper
        monkeypatch.setattr(base_scraper._http_session, 'get',
                            lambda *a, **kw: fake_get(*a, **kw))
        # Skip the post-download finalize step — we only care about the GET.
        monkeypatch.setattr('services.image_utils.finalize_downloaded_image',
                            lambda *a, **kw: None)

        dest = tmp_path / 'boxart' / 'fake.png'
        result = base_scraper.download_image(
            'https://upstream.example.com/img.png', str(dest),
        )
        assert result is True
        assert observed.get('ips') == [ip], (
            f"GET observed ips={observed!r} — expected pin to inject {ip!r}; "
            "if this is empty or different, pin_host_ip() is not wrapping the GET."
        )

    def test_metadata_merger_download_and_finalize_pins_ip(self, tmp_path, monkeypatch):
        """metadata_merger._download_and_finalize must also pin the IP."""
        ip = self._patch_validators(monkeypatch, pinned_ip='203.0.113.66')
        fake_get, observed = self._capture_pin_during_get()

        from scraper import metadata_merger
        monkeypatch.setattr(metadata_merger.requests, 'get',
                            lambda *a, **kw: fake_get(*a, **kw))
        monkeypatch.setattr(metadata_merger, 'finalize_downloaded_image',
                            lambda *a, **kw: None)

        dest = tmp_path / 'boxart' / 'm.png'
        result = metadata_merger._download_and_finalize(
            'https://upstream.example.com/img.png', str(dest), 'boxart',
        )
        assert result is True
        assert observed.get('ips') == [ip]

    def test_scrape_screenscraper_download_media_pins_ip(self, tmp_path, monkeypatch):
        """ScreenScraper download_media must pin the IP."""
        ip = self._patch_validators(monkeypatch, pinned_ip='203.0.113.77')
        fake_get, observed = self._capture_pin_during_get()

        from scraper import scrape_screenscraper
        monkeypatch.setattr(scrape_screenscraper._http_session, 'get',
                            lambda *a, **kw: fake_get(*a, **kw))

        dest = tmp_path / 'media.png'
        result = scrape_screenscraper.download_media(
            'https://www.screenscraper.fr/api/media.php?x=1', str(dest),
        )
        assert result is True
        assert observed.get('ips') == [ip]

    def test_image_utils_download_model_pins_ip(self, tmp_path, monkeypatch):
        """services.image_utils._download_model must use pin_host_ip too —
        the urllib path used to follow redirects through real DNS."""
        ip = self._patch_validators(monkeypatch, pinned_ip='203.0.113.88')
        fake_get, observed = self._capture_pin_during_get()

        import services.image_utils as image_utils
        # The function imports `requests` locally; monkeypatch the module.
        import requests as _requests
        monkeypatch.setattr(_requests, 'get',
                            lambda *a, **kw: fake_get(*a, **kw))

        dest = tmp_path / 'models' / 'realesrgan.onnx'
        # Should succeed via the first URL and not raise.
        image_utils._download_model(
            'https://huggingface.co/Xenova/realesrgan-x4plus/resolve/main/model.onnx',
            str(dest),
        )
        assert observed.get('ips') == [ip]


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
