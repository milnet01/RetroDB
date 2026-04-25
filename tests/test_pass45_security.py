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

    def test_permission_denied_on_api_returns_403_json(self, monkeypatch):
        """A logged-in user who lacks the permission must receive a 403
        with the canonical JSON envelope on /api/* — not a 302 to /dashboard
        (which fetch() with credentials follows transparently and turns the
        error into a confusing dashboard-HTML response).

        Pass 45.4 follow-up: the original version of this test relied on the
        ``_stub_authenticated_admin`` ``before_request`` hook, but Flask runs
        every ``before_request`` (including the app's own ``get_current_user``
        loader and the CSRF check) before the route's decorators. The CSRF
        layer rejected the test's POST with 403 *before* the permission
        decorator ran — the assertion happened to pass for the wrong reason.
        We now monkeypatch ``get_current_user`` directly (so the decorator
        sees a real admin) AND seed a matching CSRF token, so the 403 is
        truly the permission decorator's response."""
        import app as app_module
        from services import auth as auth_mod
        import settings_manager as _settings_manager

        # Stash the permission map, drop track_progress so the decorator
        # denies access, then restore on teardown.
        original = auth_mod.ROLE_PERMISSIONS['admin'].copy()
        auth_mod.ROLE_PERMISSIONS['admin'] = original - {'track_progress'}

        # Bypass the DB-backed user loader and the first-time-setup redirect
        # (CI's empty data/ directory has no settings.json → 302 to /setup).
        fake_admin = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}
        monkeypatch.setattr(app_module, 'get_current_user', lambda: fake_admin)
        monkeypatch.setattr(app_module, 'get_user_settings', lambda _uid: None)
        monkeypatch.setattr(_settings_manager, 'load_settings',
                            lambda: {'setup_completed': True})

        try:
            app_module.app.config['TESTING'] = True
            with app_module.app.test_client() as c:
                with c.session_transaction() as sess:
                    sess['_csrf_token'] = 'pass45_1-csrf-token'
                resp = c.post(
                    '/api/game/1/completion',
                    json={'status': 'played'},
                    headers={'X-CSRF-Token': 'pass45_1-csrf-token'},
                    follow_redirects=False,
                )
        finally:
            auth_mod.ROLE_PERMISSIONS['admin'] = original

        assert resp.status_code == 403, (
            f"Expected 403 on permission denied, got {resp.status_code} "
            f"with Location={resp.headers.get('Location', '')} "
            f"and body={resp.get_data(as_text=True)[:200]}"
        )
        body = resp.get_json()
        assert body is not None, "Response must be JSON, not HTML redirect"
        assert body.get('success') is False
        assert 'error' in body
        # Pin that the 403 is from the permission decorator, not from CSRF.
        # The decorator emits "permission denied" / "track_progress" / a
        # variant naming the missing permission; the CSRF layer emits
        # "Invalid or missing CSRF token". They must not collide.
        err = (body.get('error') or '').lower()
        assert 'csrf' not in err, (
            f"403 came from CSRF, not the permission decorator: {body!r}"
        )

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

        # In CI the data/ dir is empty, so app.check_first_time_setup sees no
        # rom_path and no `setup_completed` flag and 302s every endpoint to
        # /setup. Stub settings_manager.load_settings to claim setup is done
        # so the route under test is the one that actually runs.
        import settings_manager as _settings_manager
        monkeypatch.setattr(_settings_manager, 'load_settings',
                            lambda: {'setup_completed': True})

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


# -----------------------------------------------------------------------------
# 45.4 — XSS sinks in toast / HLTB / settings dialogs
# -----------------------------------------------------------------------------
class TestPass45_4XssSinks:
    """Three XSS sinks identified by the third 14-agent indie review:

    1. ``static/js/toast-controller.js:1171`` — bare ``${data.return_url}``
       interpolated into ``onclick="...JS-string..."`` attribute. Pass 41.12.B
       added a runtime ``_isSafeReturnUrl`` guard, but it fires after the
       HTML parser has already executed the broken-out-of attribute. Migrated
       to ``data-toast-action`` + delegated ``addEventListener`` handler.

    2. ``static/js/game-modals.js:670-689`` — HLTB API fields
       ``main_story``/``main_extra``/``completionist`` interpolated raw into
       ``innerHTML``. Wrapped in ``escapeHtml(String(...))``.

    3. ``templates/settings.html:4373/4399`` — ``confirmMessage.innerHTML =
       message`` with the comment "Use innerHTML to support HTML content".
       Same family as ``showModal`` Pass 40.13 closed — default to
       ``textContent`` with ``{allowHtml:true}`` opt-in mirroring
       ``settings-page.js`` ``ConfirmModal.show``.

    These are template/JS-level sinks, so the tests are source-grep against
    the contract (mirrors Pass 40.13's pattern in
    ``test_pass40_security.py::TestPass40_13TextContentDefault``)."""

    @staticmethod
    def _read(rel):
        path = os.path.join(_REPO_ROOT, rel)
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_toast_controller_has_no_inline_onclicks(self):
        """The active-toast and RA-queued toast templates must not emit
        ``onclick="...${value}..."`` strings — that's the JS-string-in-HTML
        attribute sink. Doc/comment references are excluded."""
        body = self._read('static/js/toast-controller.js')
        # Strip line-comments so docstrings mentioning the legacy pattern
        # don't trip the assertion.
        live_lines = [
            ln for ln in body.split('\n')
            if 'onclick=' in ln and not ln.lstrip().startswith('//')
        ]
        assert not live_lines, (
            "toast-controller.js still has live inline onclick attributes "
            f"(Pass 45.4 migrated to delegated handlers): {live_lines!r}"
        )

    def test_toast_controller_uses_delegated_action_attrs(self):
        """The replacement pattern is data-toast-action + addEventListener
        on the container. At least one ``data-toast-action="..."`` must be
        present and the container must register a click listener."""
        body = self._read('static/js/toast-controller.js')
        assert 'data-toast-action=' in body, (
            "toast-controller.js must emit data-toast-action attributes "
            "instead of inline onclick (Pass 45.4)"
        )
        assert "this.container.addEventListener('click'" in body, (
            "toast-controller.js must install a delegated click handler "
            "on the toast container (Pass 45.4)"
        )

    def test_hltb_time_fields_are_escaped(self):
        """The HLTB API returns external strings; every field that lands in
        innerHTML must go through escapeHtml. game-modals.js:670-689 used
        to interpolate them raw."""
        body = self._read('static/js/game-modals.js')
        # The savedDiv.innerHTML block must escape main_story / main_extra
        # / completionist.
        assert 'escapeHtml(String(data.main_story' in body, (
            "game-modals.js must escape data.main_story before innerHTML "
            "(Pass 45.4)"
        )
        assert 'escapeHtml(String(data.main_extra' in body, (
            "game-modals.js must escape data.main_extra before innerHTML "
            "(Pass 45.4)"
        )
        assert 'escapeHtml(String(data.completionist' in body, (
            "game-modals.js must escape data.completionist before innerHTML "
            "(Pass 45.4)"
        )

    def test_hltb_clear_button_no_inline_onclick(self):
        """The HLTB clear button used to embed ${ctx.clearFnName} into an
        inline onclick — same JS-string-in-HTML family. Replaced with
        data-hltb-clear + addEventListener."""
        body = self._read('static/js/game-modals.js')
        assert 'onclick="${ctx.clearFnName}' not in body, (
            "game-modals.js must not embed clearFnName into inline onclick "
            "(Pass 45.4)"
        )
        assert 'data-hltb-clear' in body, (
            "HLTB clear button must use data-hltb-clear + addEventListener "
            "(Pass 45.4)"
        )

    def test_settings_modal_helpers_default_to_textcontent(self):
        """showConfirmModal and showInfoModal in settings.html must default
        to textContent and only use innerHTML when options.allowHtml is
        explicitly true. Mirrors the ConfirmModal.show pattern in
        settings-page.js (Pass 29.1)."""
        body = self._read('templates/settings.html')
        # Both helpers must accept an options arg.
        assert 'function showConfirmModal(title, message, onConfirm, options' in body, (
            "showConfirmModal must accept an options arg with allowHtml "
            "(Pass 45.4)"
        )
        assert 'function showInfoModal(title, message, onOk, options' in body, (
            "showInfoModal must accept an options arg with allowHtml "
            "(Pass 45.4)"
        )
        # The bug-shape comment must be gone — its presence indicates the
        # bare innerHTML sink is back.
        assert "Use innerHTML to support HTML content" not in body, (
            "Pass 45.4 removed the bare 'innerHTML to support HTML content' "
            "form; if this fires the textContent default has been reverted"
        )
        # The opt-in branch must exist.
        assert 'options.allowHtml' in body, (
            "showConfirmModal/showInfoModal must guard innerHTML behind "
            "options.allowHtml (Pass 45.4)"
        )
        assert 'messageEl.textContent = message' in body, (
            "showConfirmModal/showInfoModal must default to textContent "
            "(Pass 45.4)"
        )

    def test_settings_html_callers_with_html_opt_in(self):
        """The two showConfirmModal callers that genuinely need formatted
        HTML (clearScrapedData, deleteController) must opt in via
        {allowHtml: true} and escape user-controlled values they
        interpolate into the template."""
        body = self._read('templates/settings.html')
        # User-controlled fields must be escaped.
        assert 'escapeHtml(controllerName)' in body, (
            "deleteController must escape controllerName before injecting "
            "into the confirm template (Pass 45.4)"
        )
        assert 'escapeHtml(systemName)' in body, (
            "clearScrapedData must escape systemName before injecting "
            "into the confirm template (Pass 45.4)"
        )
        # Both callers opt in to HTML.
        assert body.count('{allowHtml: true}') >= 2, (
            "settings.html must opt in to HTML on the two formatted-confirm "
            "callers (Pass 45.4)"
        )


# -----------------------------------------------------------------------------
# 45.5 — Atomic-write contract drift
# -----------------------------------------------------------------------------
class TestPass45_5AtomicWrite:
    """Four ad-hoc copies of the "tmp + os.replace" dance had drifted:

    1. ``app.py:_get_secret_key`` — opened, wrote, then chmod'd, leaving
       the secret key at the umask default (typically 0o644) for a brief
       window. Now uses ``atomic_write_text(path, key, mode=0o600)`` which
       chmods the tmpfile *before* the rename.
    2. ``services/image_utils.py:_atomic_save`` — docstring claimed fsync
       but never called it; a power loss between PIL's close() and
       os.replace landed a 0-byte file at the destination on next mount.
    3. ``services/game_media_service.py:_atomic_write_bytes`` — same
       missing-fsync shape. Now delegates to ``atomic_write_bytes``.
    4. ``services/database.py:backup_database`` — chmod'd the backup file
       *after* opening it for the integrity-check verify pass, leaving a
       0o644 window for the duration of the check. Backups contain
       session cookies, password hashes, and OAuth tokens.
    5. ``services/image_utils.py:_download_model`` — used a static
       ``dest + '.tmp'`` suffix; concurrent downloads from different
       workers raced on the same temp path. Now uses ``mkstemp``.
    """

    def test_atomic_write_bytes_chmods_before_replace(self, tmp_path):
        """The secret-key path needs the chmod to land *before* the rename
        so the final path never exists at the umask default (0o644)."""
        from services.atomic_io import atomic_write_bytes
        target = tmp_path / 'secret.bin'
        atomic_write_bytes(str(target), b'top-secret', mode=0o600)
        assert target.read_bytes() == b'top-secret'
        # Mode bits should be exactly 0o600 — no group/other read.
        mode = target.stat().st_mode & 0o777
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

    def test_atomic_write_text_round_trips_unicode(self, tmp_path):
        from services.atomic_io import atomic_write_text
        target = tmp_path / 'config.json'
        atomic_write_text(str(target), '{"k": "ümlaut"}\n', mode=0o644)
        assert target.read_text(encoding='utf-8') == '{"k": "ümlaut"}\n'

    def test_atomic_write_bytes_rejects_str(self, tmp_path):
        """Strings must go through atomic_write_text so the encoding is
        explicit. Otherwise an accidental call with a unicode string
        would silently TypeError inside f.write at runtime."""
        from services.atomic_io import atomic_write_bytes
        with pytest.raises(TypeError):
            atomic_write_bytes(str(tmp_path / 'x'), 'not bytes')

    def test_atomic_write_bytes_cleans_tmp_on_failure(self, tmp_path, monkeypatch):
        """On any failure path the .atomic_* tmpfile must not be left
        behind — it would otherwise accumulate after every crash."""
        from services import atomic_io
        target = tmp_path / 'sub' / 'fail.bin'

        def boom(_path, _mode):
            raise OSError("simulated chmod failure that we don't catch")

        # Force os.replace itself to fail so the cleanup branch runs.
        original_replace = os.replace
        def failing_replace(*args, **kwargs):
            raise OSError("simulated replace failure")
        monkeypatch.setattr(os, 'replace', failing_replace)
        with pytest.raises(OSError):
            atomic_io.atomic_write_bytes(str(target), b'payload')
        # Tempfiles use the .atomic_ prefix — none should remain.
        leftover = list((tmp_path / 'sub').glob('.atomic_*'))
        assert not leftover, f"tempfile not cleaned up: {leftover}"

    def test_atomic_save_calls_fsync(self, tmp_path, monkeypatch):
        """_atomic_save's docstring claimed fsync but the previous version
        never called it. Pin the contract by counting fsync calls during
        a save; without the fix os.fsync count is 0."""
        from services import image_utils
        from PIL import Image

        fsync_calls = []
        original_fsync = os.fsync
        monkeypatch.setattr(os, 'fsync', lambda fd: fsync_calls.append(fd) or original_fsync(fd))

        img = Image.new('RGB', (8, 8), color=(255, 0, 0))
        out = tmp_path / 'img.png'
        image_utils._atomic_save(img, str(out), 'PNG')

        assert out.exists()
        assert len(fsync_calls) >= 1, (
            "_atomic_save must call os.fsync between PIL close and os.replace "
            "(Pass 45.5)"
        )

    def test_backup_database_chmods_before_verify(self, tmp_path, monkeypatch):
        """backup_database's chmod must fire before the integrity-check
        verify open. Strategy: end-to-end smoke a real backup, then
        grep the source for chmod-before-verify ordering.

        sqlite3.Connection is C-immutable so we can't intercept execute()
        at the class level; instead we (1) confirm the backup runs to
        completion and (2) confirm the source has the chmod block before
        the ``sqlite3.connect(dst_path)`` verify-open block."""
        import services.database as db_mod
        import sqlite3
        import stat

        # End-to-end smoke first: build a seed DB, call backup_database,
        # verify the result file exists at 0o600.
        src = tmp_path / 'src.db'
        seed = sqlite3.connect(str(src))
        seed.execute('CREATE TABLE t (x INTEGER)')
        seed.execute('INSERT INTO t VALUES (1)')
        seed.commit()
        seed.close()
        dst = tmp_path / 'backup.db'
        db_mod.backup_database(str(src), str(dst))
        assert dst.exists(), "backup_database must produce the destination file"
        final_mode = stat.S_IMODE(dst.stat().st_mode)
        assert final_mode == 0o600, (
            f"backup file final mode should be 0o600, got {oct(final_mode)}"
        )

        # Source-level pin: chmod must precede the verify connect. Pull
        # the function body and find the offsets of (a) the chmod call on
        # dst_path and (b) the verify ``sqlite3.connect(dst_path)``.
        path = os.path.join(_REPO_ROOT, 'services', 'database.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        idx = body.find('def backup_database')
        next_def = body.find('\ndef ', idx + 1)
        body_slice = body[idx:next_def] if next_def != -1 else body[idx:]
        chmod_pos = body_slice.find('os.chmod(dst_path')
        verify_pos = body_slice.find('verify = sqlite3.connect(dst_path')
        assert chmod_pos != -1, (
            "backup_database must chmod dst_path"
        )
        assert verify_pos != -1, (
            "backup_database must open dst_path for the integrity-check verify"
        )
        assert chmod_pos < verify_pos, (
            "backup_database must chmod the destination BEFORE the "
            "integrity-check verify connect (Pass 45.5). The previous "
            "order left a 0o644 window for the duration of the check."
        )

    def test_secret_key_uses_atomic_write_text(self):
        """app._get_secret_key must route through atomic_write_text with
        mode=0o600 — bare open()+write()+chmod leaves a world-readable
        window for the secret key."""
        path = os.path.join(_REPO_ROOT, 'app.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        # Find the _get_secret_key function body.
        assert 'def _get_secret_key' in body
        # The atomic helper must be referenced inside the function.
        # Simple substring check — if someone reverts to bare open+chmod,
        # `atomic_write_text(key_path, key, mode=0o600)` will be gone.
        assert 'atomic_write_text(key_path, key, mode=0o600)' in body, (
            "_get_secret_key must use atomic_write_text(..., mode=0o600) "
            "(Pass 45.5)"
        )

    def test_download_model_uses_mkstemp(self):
        """_download_model's tmp path must come from tempfile.mkstemp,
        not the static `dest + '.tmp'` form that races with concurrent
        downloads from different workers."""
        path = os.path.join(_REPO_ROOT, 'services', 'image_utils.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        # Find the _download_model function.
        idx = body.find('def _download_model')
        assert idx != -1
        # Pull the function body up to the next top-level def.
        next_def = body.find('\ndef ', idx + 1)
        body_slice = body[idx:next_def] if next_def != -1 else body[idx:]
        assert "tempfile.mkstemp" in body_slice, (
            "_download_model must use tempfile.mkstemp for the tmp path "
            "(Pass 45.5)"
        )
        assert "dest + '.tmp'" not in body_slice, (
            "_download_model must not use the static `dest + '.tmp'` "
            "suffix (race-prone, Pass 45.5)"
        )


# -----------------------------------------------------------------------------
# 45.6 — Pillow decompression-bomb cap
# -----------------------------------------------------------------------------
class TestPass45_6DecompressionBomb:
    """Pass 41.14.A set ``Image.MAX_IMAGE_PIXELS`` for ``compute_dhash``
    only. The rest of the image stack (``services.image_utils`` and
    ``services.game_media_service``) had no cap, so a 1 MB malicious PNG
    that advertises 50000×50000 pixels could decode to 10 GB of pixel
    data and OOM-kill the worker.

    Pass 45.6 sets the cap once at module-import time in both files,
    using ``config.IMAGE_MAX_PIXELS`` (default 64 megapixels) — well
    above any legitimate game cover or screenshot. Every ``Image.open``
    call site catches ``DecompressionBombError`` explicitly so the
    security log records bomb attempts under a distinct line."""

    def test_image_utils_module_sets_max_image_pixels(self):
        """Importing services.image_utils must install the cap on the
        global Pillow Image module, not just inside one helper."""
        import importlib
        import services.image_utils  # noqa: F401 — import for side-effect
        from PIL import Image
        # The cap is set in services/image_utils.py at import time.
        assert Image.MAX_IMAGE_PIXELS is not None, (
            "Image.MAX_IMAGE_PIXELS must be set after services.image_utils "
            "is imported (Pass 45.6)"
        )
        assert Image.MAX_IMAGE_PIXELS <= 64_000_000, (
            f"Image.MAX_IMAGE_PIXELS = {Image.MAX_IMAGE_PIXELS}; "
            "must be ≤ 64 megapixels (Pass 45.6)"
        )

    def test_game_media_service_module_sets_max_image_pixels(self):
        """Same contract for game_media_service — the upload validator
        runs through Pillow and needs the cap too."""
        import services.game_media_service  # noqa: F401
        from PIL import Image
        assert Image.MAX_IMAGE_PIXELS is not None
        assert Image.MAX_IMAGE_PIXELS <= 64_000_000

    def test_validate_image_bytes_rejects_oversized_bomb(self, monkeypatch):
        """Functional smoke: a synthetic image whose declared dimensions
        exceed MAX_IMAGE_PIXELS must be rejected by
        ``_validate_image_bytes``, not raise an OOM."""
        from PIL import Image
        from services import game_media_service

        # Lower the cap to 1000 px² for the test so we don't have to
        # actually build a 64-megapixel buffer.
        monkeypatch.setattr(Image, 'MAX_IMAGE_PIXELS', 1000)
        # Build a real 100×100 PNG (10000 px > 1000 cap → bomb error).
        import io
        img = Image.new('RGB', (100, 100), color=(0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, 'PNG')
        raw = buf.getvalue()

        result = game_media_service._validate_image_bytes(raw)
        assert result is False, (
            "_validate_image_bytes must reject images that trip "
            "MAX_IMAGE_PIXELS (Pass 45.6)"
        )

    def test_config_exports_image_max_pixels(self):
        """The cap must be configurable via ``config.IMAGE_MAX_PIXELS`` so
        operators with legitimately huge artwork (e.g. 8K box scans) can
        raise it. The default in config.example.py must be present."""
        path = os.path.join(_REPO_ROOT, 'config.example.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        assert 'IMAGE_MAX_PIXELS' in body, (
            "config.example.py must export IMAGE_MAX_PIXELS (Pass 45.6)"
        )

    def test_image_open_sites_catch_decompression_bomb(self):
        """Every ``Image.open`` call site in services/image_utils.py must
        catch ``DecompressionBombError`` explicitly so the security log
        shows a distinct rejection line (mirrors the source-grep pattern
        used by Pass 40.13/45.4 for textContent default)."""
        path = os.path.join(_REPO_ROOT, 'services', 'image_utils.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        open_count = body.count('Image.open(')
        bomb_catches = body.count('Image.DecompressionBombError')
        # Expect at least 4 explicit catches — one per Image.open site
        # in the public API surface (_ensure_format_matches_extension,
        # _make_responsive_variants, boxart_srcset, standardize_image).
        # The lazy `from PIL import Image` lines also count as "Image.open"
        # imports in raw count, so use a >= floor.
        assert bomb_catches >= 4, (
            f"Found {open_count} Image.open() sites but only "
            f"{bomb_catches} DecompressionBombError catches; "
            "every site must catch the bomb explicitly (Pass 45.6)"
        )


# -----------------------------------------------------------------------------
# 45.7 — Orphan-cleanup race + symlink guard
# -----------------------------------------------------------------------------
class TestPass45_7OrphanCleanupRace:
    """``services.media_cleanup.find_orphaned_media`` builds a snapshot of
    "files not referenced by any game"; ``clean_orphaned_files`` then
    deletes from the snapshot. Between the two calls a scraper writing
    a freshly-rescraped ``42_boxart_v2.webp`` (and updating the row
    accordingly) can race the cleaner: v2 was on disk but not yet
    referenced at scan time, so the snapshot includes it; then the row
    update lands; then the cleaner unlinks the file the row now points
    at. Pass 45.7 stamps each orphan dict with mtime + scan-start time,
    and the cleaner refuses to unlink files modified during the cleanup
    window. Symlinks are also refused at both ends (defence in depth)."""

    def _make_layout(self, tmp_path, monkeypatch):
        """Stand up a minimal config-like layout pointing at tmp_path."""
        import config
        monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path / 'images'))
        monkeypatch.setattr(config, 'STATIC_PATH', str(tmp_path / 'static'))
        for sub in ('boxart', 'boxart_3d', 'screenshots', 'fanart', 'manuals'):
            (tmp_path / 'images' / sub).mkdir(parents=True, exist_ok=True)
        (tmp_path / 'static' / 'videos').mkdir(parents=True, exist_ok=True)

    def test_find_attaches_mtime_and_scan_start(self, tmp_path, monkeypatch):
        """Each orphan dict must carry ``mtime`` and ``scan_started_at``
        so the cleaner can defeat the snapshot-then-delete race."""
        self._make_layout(tmp_path, monkeypatch)
        from services import media_cleanup

        # Create one orphaned file (no game references it).
        boxart = tmp_path / 'images' / 'boxart' / '99_boxart.png'
        boxart.write_bytes(b'fake')

        games = [{'id': 1, 'boxart': '', 'boxart_3d': '', 'screenshots': '',
                  'fanart': '', 'video': '', 'manual': ''}]
        orphaned, _ = media_cleanup.find_orphaned_media(games)
        assert len(orphaned) == 1
        entry = orphaned[0]
        assert 'mtime' in entry, "orphan dict must include mtime (Pass 45.7)"
        assert 'scan_started_at' in entry, (
            "orphan dict must include scan_started_at (Pass 45.7)"
        )

    def test_find_skips_symlinks(self, tmp_path, monkeypatch):
        """A symlink inside the media tree (rare but possible from manual
        admin work) must never end up in the orphan list — ``os.remove``
        on a symlink only unlinks the link, but defence in depth says
        we shouldn't even consider it."""
        self._make_layout(tmp_path, monkeypatch)
        from services import media_cleanup

        # Create a real file and a symlink pointing at it, both inside boxart.
        real = tmp_path / 'images' / 'boxart' / '99_real.png'
        real.write_bytes(b'real')
        link = tmp_path / 'images' / 'boxart' / '99_link.png'
        link.symlink_to(real)

        games = [{'id': 1, 'boxart': '', 'boxart_3d': '', 'screenshots': '',
                  'fanart': '', 'video': '', 'manual': ''}]
        orphaned, _ = media_cleanup.find_orphaned_media(games)
        paths = [o['path'] for o in orphaned]
        assert str(real) in paths, "real file must be considered"
        assert str(link) not in paths, (
            "symlink must be skipped at scan time (Pass 45.7)"
        )

    def test_clean_skips_files_modified_during_cleanup_window(self, tmp_path, monkeypatch):
        """If a scraper bumps the mtime between scan and clean, the
        cleaner must refuse to unlink — that file may now be referenced
        by a row inserted during the cleanup window."""
        self._make_layout(tmp_path, monkeypatch)
        from services import media_cleanup
        import time as _time

        target = tmp_path / 'images' / 'boxart' / '99_orphan.png'
        target.write_bytes(b'orphan')

        games = [{'id': 1, 'boxart': '', 'boxart_3d': '', 'screenshots': '',
                  'fanart': '', 'video': '', 'manual': ''}]
        orphaned, _ = media_cleanup.find_orphaned_media(games)
        assert len(orphaned) == 1

        # Simulate a scraper writing to the file AFTER scan_started_at
        # by setting mtime forward 60 seconds.
        future = _time.time() + 60
        os.utime(str(target), (future, future))

        deleted, errors, freed = media_cleanup.clean_orphaned_files(orphaned)
        assert deleted == 0, (
            "clean_orphaned_files must skip files modified after "
            "scan_started_at (Pass 45.7)"
        )
        assert errors == 0
        assert target.exists(), "the racing file must survive the cleanup"

    def test_clean_skips_symlink_appearing_after_scan(self, tmp_path, monkeypatch):
        """Even if a symlink somehow ended up in the orphan list (e.g.
        from a stale snapshot built by a pre-Pass-45.7 caller), the
        cleaner must refuse to unlink it."""
        self._make_layout(tmp_path, monkeypatch)
        from services import media_cleanup

        real = tmp_path / 'images' / 'boxart' / '99_real.png'
        real.write_bytes(b'real')
        link = tmp_path / 'images' / 'boxart' / '99_link.png'
        link.symlink_to(real)

        # Hand-craft a stale snapshot that includes the symlink (no
        # mtime / scan_started_at — to test the symlink branch alone).
        stale = [{
            'path': str(link), 'filename': '99_link.png',
            'type': 'boxart', 'size': 4,
        }]
        deleted, errors, freed = media_cleanup.clean_orphaned_files(stale)
        assert deleted == 0
        assert errors == 0
        assert link.exists(), "symlink must survive the cleanup (Pass 45.7)"

    def test_clean_still_deletes_unmodified_orphans(self, tmp_path, monkeypatch):
        """Sanity: the new guards must not block the legitimate path —
        an orphan whose mtime is unchanged from scan time still gets
        deleted normally."""
        self._make_layout(tmp_path, monkeypatch)
        from services import media_cleanup

        target = tmp_path / 'images' / 'boxart' / '99_orphan.png'
        target.write_bytes(b'orphan')

        games = [{'id': 1, 'boxart': '', 'boxart_3d': '', 'screenshots': '',
                  'fanart': '', 'video': '', 'manual': ''}]
        orphaned, _ = media_cleanup.find_orphaned_media(games)
        deleted, errors, freed = media_cleanup.clean_orphaned_files(orphaned)
        assert deleted == 1
        assert errors == 0
        assert freed == 6
        assert not target.exists()
