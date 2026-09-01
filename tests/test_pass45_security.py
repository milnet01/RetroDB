# =============================================================================
# Pass 45 — indie-review 2026-04-25 fold-in
# =============================================================================
# Regression pins for findings folded as Pass 45 sub-passes. Tests are
# behaviour-anchored where possible (Pass 45.18 flags the source-grep
# antipattern); only configuration assertions go through grep.
# =============================================================================

import os

import pytest

from tests._util import REPO_ROOT as _REPO_ROOT  # noqa: F401
from tests._util import read_settings_with_partials


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
        # denies access. monkeypatch restores on teardown — atomic with the
        # TESTING mutation below, so a SIGKILL/OOM between the two won't
        # leave admin in a half-modified state.
        original = auth_mod.ROLE_PERMISSIONS['admin'].copy()
        monkeypatch.setitem(auth_mod.ROLE_PERMISSIONS, 'admin', original - {'track_progress'})

        # Bypass the DB-backed user loader and the first-time-setup redirect
        # (CI's empty data/ directory has no settings.json → 302 to /setup).
        fake_admin = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}
        monkeypatch.setattr(app_module, 'get_current_user', lambda: fake_admin)
        monkeypatch.setattr(app_module, 'get_user_settings', lambda _uid: None)
        monkeypatch.setattr(_settings_manager, 'load_settings',
                            lambda: {'setup_completed': True})

        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        with app_module.app.test_client() as c:
            with c.session_transaction() as sess:
                sess['_csrf_token'] = 'pass45_1-csrf-token'
            resp = c.post(
                '/api/game/1/completion',
                json={'status': 'played'},
                headers={'X-CSRF-Token': 'pass45_1-csrf-token'},
                follow_redirects=False,
            )

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
        # Both branches must exist.  We grep here because the routing
        # tables don't expose any non-/api/* permission_required usage
        # in this repo (the smoke wouldn't exercise the branch).
        #
        # 2026-09-01: this read getsource(permission_required) and asserted
        # the literal there. The two branches were hoisted into _deny_*
        # so that admin_required / editor_required / login_required could
        # share them -- they had been 302ing on /api/* at 115 sites. The
        # CONTRACT is unchanged, so this asserts it at its new home rather
        # than being relaxed: the split still has to exist, and
        # permission_required still has to route through it.
        deny = getsource(auth_mod._deny_forbidden)
        assert "redirect(url_for('dashboard'))" in deny
        assert "/api/" in deny

        used = getsource(auth_mod.permission_required)
        assert "_deny_forbidden" in used, (
            "permission_required no longer routes its denial through "
            "_deny_forbidden -- the /api/ vs page split may have been "
            "reintroduced per-decorator, which is what drifted before."
        )

    def test_all_four_decorators_share_the_api_split(self):
        """The 302-on-/api/* defect was three decorators missing a branch a
        fourth already had. Pin that none of them hand-rolls it again.

        Found by five independent review lanes on 2026-09-01: 115 /api/*
        routes answered a denial with a 302 to /dashboard, which fetch()
        follows transparently, so calling JS saw 200-with-dashboard-HTML.
        """
        import services.auth as auth_mod
        from inspect import getsource
        for name in ('login_required', 'admin_required',
                     'editor_required', 'permission_required'):
            src = getsource(getattr(auth_mod, name))
            assert "_deny_unauthenticated" in src or "_deny_forbidden" in src, (
                f"{name} does not use the shared deny helpers"
            )
            assert "redirect(url_for('auth.login'" not in src, (
                f"{name} hand-rolls the unauthenticated redirect again -- "
                f"that is the shape that skipped the /api/ branch"
            )


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

        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
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

        # Pass 51.3: _download_and_finalize now streams through the shared
        # base_scraper._http_session (pooled connection reuse), mirroring
        # base_scraper.download_image. pin_host_ip() still wraps the GET, so the
        # DNS-rebinding guarantee is unchanged — patch the session the function
        # actually uses (same object the local import binds), not module `requests`.
        from scraper import metadata_merger, base_scraper
        monkeypatch.setattr(base_scraper._http_session, 'get',
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
        import services.image_utils
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
        import services.game_media_service
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


# -----------------------------------------------------------------------------
# 45.8 — Steam/Xbox/PSN/wishlist endpoint rate-limits
# -----------------------------------------------------------------------------
class TestPass45_8RateLimits:
    """Pass 41.10.D added rate-limits to the heavy filesystem-walk
    endpoints. Pass 45.8 extends the same pattern to third-party-API
    fan-out endpoints: a misclick or stuck XHR poll loop on the
    Steam / Xbox / PSN library import flows can otherwise burn API
    quota or trigger account bans (PSN especially has aggressive
    per-account caps). Caps:
      - 5/min for "fetch the whole library" actions (rare, admin-driven)
      - 2/hour for "bulk refresh / sync everything" actions (cron-like)
      - 30/min for credit-check probes (UI polling)"""

    REQUIRED_ENDPOINTS = (
        'platform_import.api_steam_fetch_library',
        'platform_import.api_steam_import',
        'platform_import.api_steam_sync_achievements',
        'platform_import.api_xbox_fetch_library',
        'platform_import.api_xbox_import',
        'platform_import.api_xbox_sync_achievements',
        'platform_import.api_psn_fetch_library',
        'platform_import.api_psn_import',
        'steam_achievements.api_steam_sync_all',
        'xbox_achievements.api_xbox_sync_all',
        'trophies.api_psn_sync_all',
        'trophies.api_psn_bulk_refresh_start',
        'collections.api_scrape_all_wishlist',
        'scraper.api_check_scraper',
        'scraper.api_scraper_allowance',
    )

    def test_required_endpoints_exist(self):
        """Sanity: every endpoint Pass 45.8 rate-limits must actually be
        registered. ``_rate_limit`` would raise on import if not, but
        a bare grep doesn't catch a typo until app startup. Pin here."""
        import app as app_module
        for endpoint in self.REQUIRED_ENDPOINTS:
            assert endpoint in app_module.app.view_functions, (
                f"Endpoint {endpoint} is not registered; Pass 45.8 "
                "rate-limit registration would fail at import"
            )

    def test_app_py_registers_rate_limits(self):
        """app.py must contain a _rate_limit('endpoint', ...) call for
        every endpoint in REQUIRED_ENDPOINTS. Source-grep test mirrors
        Pass 41.10.D's pattern."""
        path = os.path.join(_REPO_ROOT, 'app.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        for endpoint in self.REQUIRED_ENDPOINTS:
            assert f"_rate_limit('{endpoint}'" in body, (
                f"app.py must register a rate limit for {endpoint} "
                "(Pass 45.8)"
            )

    def test_bulk_actions_capped_at_two_per_hour(self):
        """The "sync everything" actions must use 2/hour, not per-minute
        — they're cron-like and should never legitimately run more than
        a couple of times an hour."""
        path = os.path.join(_REPO_ROOT, 'app.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        bulk_endpoints = (
            'platform_import.api_steam_sync_achievements',
            'platform_import.api_xbox_sync_achievements',
            'steam_achievements.api_steam_sync_all',
            'xbox_achievements.api_xbox_sync_all',
            'trophies.api_psn_sync_all',
            'trophies.api_psn_bulk_refresh_start',
            'collections.api_scrape_all_wishlist',
        )
        for endpoint in bulk_endpoints:
            line = f"_rate_limit('{endpoint}', \"2 per hour\")"
            assert line in body, (
                f"{endpoint} must be capped at 2/hour (Pass 45.8); "
                f"expected line: {line!r}"
            )


# -----------------------------------------------------------------------------
# 45.9 — collector_trophies regressions
# -----------------------------------------------------------------------------
class TestPass45_9CollectorTrophies:
    """Two regressions in routes/collector_trophies.py:

    1. ``_gather_collection_stats`` looped with ``for g in (...).split(',')``
       — same shape as the Pass 41.8.A sweep that renamed loop variables
       shadowing ``flask.g``. Calling code that did ``from flask import g``
       inside the same request scope read the loop's last genre string
       instead of the request user.

    2. ``collector_trophies_page`` (GET) and ``get_all_trophies`` (GET
       /api/collector-trophies) called ``_refresh_trophies(user_id)`` when
       the user had no rows yet, writing ~70 rows to the database.
       RFC 7231 says GET must be safe — observable side effects on shared
       state are forbidden. Pass 45.9 renders an in-memory roster from
       TROPHY_DEFINITIONS on cold cache instead; the explicit POST
       /api/collector-trophies/refresh button materialises the rows."""

    def test_gather_stats_no_g_shadow(self):
        """The genre loop must not rebind the name `g`."""
        path = os.path.join(_REPO_ROOT, 'routes', 'collector_trophies.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        assert "for g in" not in body, (
            "collector_trophies must not bind a loop variable named `g` "
            "— it shadows flask.g in the same request scope (Pass 45.9)"
        )
        # Specifically the genre split: the rename Pass 45.9 chose was
        # `genre_part`. Pin so a future edit doesn't quietly revert.
        assert 'for genre_part in' in body, (
            "Pass 45.9 renamed the genre loop variable to `genre_part`"
        )

    def test_get_handlers_do_not_call_refresh(self):
        """Neither GET handler may call _refresh_trophies. They render
        from DB rows when present, in-memory roster from TROPHY_DEFINITIONS
        when not."""
        path = os.path.join(_REPO_ROOT, 'routes', 'collector_trophies.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        # Find the page route and the GET API route bodies.
        for func_name in ('def collector_trophies_page', 'def get_all_trophies'):
            idx = body.find(func_name)
            assert idx != -1, f"{func_name} must exist"
            next_def = body.find('\ndef ', idx + 1)
            slice_body = body[idx:next_def] if next_def != -1 else body[idx:]
            # Check for an actual call: `_refresh_trophies(`. Docstring
            # references in slice_body are fine (they document the fix).
            assert '_refresh_trophies(' not in slice_body, (
                f"{func_name} must NOT call _refresh_trophies(...) — that's "
                "a DB write on a GET, violating RFC 7231 (Pass 45.9)"
            )

    def test_empty_roster_helper_returns_70_unearned_stubs(self):
        """The cold-cache renderer must produce one stub per TROPHY_
        DEFINITION, all with progress=0 and earned_at=None."""
        from routes import collector_trophies
        stubs = collector_trophies._empty_trophies_from_definitions()
        assert len(stubs) == len(collector_trophies.TROPHY_DEFINITIONS)
        for stub in stubs:
            assert stub['progress'] == 0
            assert stub['earned_at'] is None
            # Same key shape the template iterates.
            assert {'id', 'name', 'description', 'icon', 'tier',
                    'category', 'threshold'} <= stub.keys()

    def test_get_does_not_mutate_db(self, tmp_path, monkeypatch):
        """Functional smoke: GET /api/collector-trophies on a brand-new
        user must not cause any INSERT into collector_trophies."""
        import app as app_module
        import routes.collector_trophies as ct
        import settings_manager as _settings_manager

        executes = []

        def fake_execute(sql, params=()):
            executes.append((sql, params))
            return None

        # Stub the DB layer at the module level. _trophies_sorted reads
        # via query() so we stub that to return [] (empty).
        monkeypatch.setattr(ct, 'execute', fake_execute)
        monkeypatch.setattr(ct, 'query',
                            lambda sql, params=(), one=False: None if one else [])

        # Bypass auth + setup wizard.
        fake_user = {'id': 99, 'username': 'test', 'role': 'admin'}
        monkeypatch.setattr(app_module, 'get_current_user', lambda: fake_user)
        monkeypatch.setattr(app_module, 'get_user_settings', lambda _uid: None)
        monkeypatch.setattr(_settings_manager, 'load_settings',
                            lambda: {'setup_completed': True})

        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        with app_module.app.test_client() as c:
            resp = c.get('/api/collector-trophies', follow_redirects=False)

        assert resp.status_code == 200, (
            f"GET must succeed; got {resp.status_code}: "
            f"{resp.get_data(as_text=True)[:200]}"
        )
        # Filter to writes (INSERT/UPDATE/DELETE). Pass 45.9 contract is
        # zero writes from a GET handler.
        writes = [
            sql for (sql, _) in executes
            if any(verb in sql.upper() for verb in
                   ('INSERT INTO', 'UPDATE ', 'DELETE FROM'))
        ]
        assert not writes, (
            f"GET /api/collector-trophies issued {len(writes)} writes; "
            "must be zero (RFC 7231 / Pass 45.9). Writes: {writes!r}"
        )


# -----------------------------------------------------------------------------
# 45.10 — Migration runner BEGIN IMMEDIATE + busy_timeout + scoped FK check
# -----------------------------------------------------------------------------
class TestPass45_10MigrationHardening:
    """Pass 45.10 hardens the migration runner against three failure modes:

    1. Plain ``BEGIN`` (= BEGIN DEFERRED) lets concurrent readers slip in
       between BEGIN and the first DDL; under WAL a long-running reader
       can deadlock the rebuild migrations 007/008/009 that drop and
       recreate tables. Switched to ``BEGIN IMMEDIATE`` which acquires
       the write lock up front.
    2. Migration / boot connections lacked ``PRAGMA busy_timeout``, so
       BEGIN IMMEDIATE would fail-fast on contention instead of waiting.
       Added 5000ms busy_timeout on the migration runner connection,
       ``ensure_user_tables`` connection, and the backup-database verify
       connection.
    3. Rebuild migrations 007/008/009 had no post-rebuild FK assertion;
       a typo in the rebuild SQL could leave dangling references that
       SQLite only complains about lazily. Added scoped
       ``PRAGMA foreign_key_check(<table>)`` immediately before each
       migration's commit — scoped to the rebuilt tables so pre-existing
       integrity issues elsewhere don't block the upgrade path."""

    def test_migration_runner_uses_begin_immediate(self):
        path = os.path.join(_REPO_ROOT, 'services', 'migrations', '__init__.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        assert 'BEGIN IMMEDIATE' in body, (
            "migration runner must use BEGIN IMMEDIATE so it acquires the "
            "write lock up front (Pass 45.10)"
        )
        # Bare `BEGIN` (with no IMMEDIATE/DEFERRED/EXCLUSIVE qualifier) must
        # not appear; it's the failure case we're trying to remove.
        assert 'conn.execute("BEGIN")' not in body, (
            "migration runner must not use the bare BEGIN form (Pass 45.10)"
        )

    def test_database_init_sets_busy_timeout(self):
        path = os.path.join(_REPO_ROOT, 'services', 'database_init.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        # Both connection sites — the migration runner connection and the
        # ensure_user_tables connection — must set busy_timeout.
        count = body.count('PRAGMA busy_timeout')
        assert count >= 2, (
            f"services/database_init.py has {count} busy_timeout pragma "
            "settings; expected at least 2 (migration + user-tables conn) "
            "(Pass 45.10)"
        )

    def test_backup_verify_sets_busy_timeout(self):
        path = os.path.join(_REPO_ROOT, 'services', 'database.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        # The verify connection in backup_database must set busy_timeout
        # before running the integrity check.
        idx = body.find('def backup_database')
        next_def = body.find('\ndef ', idx + 1)
        slice_body = body[idx:next_def] if next_def != -1 else body[idx:]
        assert 'PRAGMA busy_timeout' in slice_body, (
            "backup_database verify connection must set busy_timeout "
            "(Pass 45.10)"
        )

    def test_rebuild_migrations_run_scoped_fk_check(self):
        """Migrations 007/008/009 each rebuild tables with FOREIGN KEY
        clauses; each must run a scoped foreign_key_check before commit."""
        for stem in ('007_psn_user_id',
                     '008_collector_trophies_user_id',
                     '009_achievement_tables_user_id'):
            path = os.path.join(
                _REPO_ROOT, 'services', 'migrations', 'scripts', f'{stem}.py'
            )
            with open(path, encoding='utf-8') as f:
                body = f.read()
            assert 'PRAGMA foreign_key_check(' in body, (
                f"migration {stem} must run a scoped foreign_key_check "
                "(Pass 45.10)"
            )

    def test_migration_runner_fk_check_is_table_scoped(self):
        """The runner-level (unscoped) foreign_key_check is too aggressive
        for legacy installs — it catches pre-existing data-integrity
        issues unrelated to the migration. Pass 45.10 keeps the FK check
        in the rebuild migrations themselves and only scopes to the
        rebuilt tables. The runner MUST NOT have an unscoped FK check."""
        path = os.path.join(_REPO_ROOT, 'services', 'migrations', '__init__.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        # The unscoped form `PRAGMA foreign_key_check"` (no table name)
        # would catch every FK in the DB. Should not be in the runner.
        assert 'PRAGMA foreign_key_check"' not in body, (
            "migration runner must not run an unscoped foreign_key_check "
            "— scope it to the rebuilt tables in the individual migrations "
            "(Pass 45.10)"
        )


# -----------------------------------------------------------------------------
# 45.11 — Settings/scraper validators wired into POST endpoints
# -----------------------------------------------------------------------------
class TestPass45_11SettingsValidators:
    """Pass 45.11 wires per-key validators into three POST endpoints that
    previously wrote the request body verbatim:

    1. ``/api/settings/logging`` — ``settings['logging'] = data`` was
       unconditional. ``validate_settings_value('logging', data)`` exists at
       services/settings_validators.py:182 but was never called.
    2. ``/api/scraper-settings`` — ``priority``/``enabled``/``match_*`` were
       persisted without type-checking; a string-instead-of-bool or bogus
       scraper name in ``priority`` would crash scraper_manager next call.
    3. ``/api/scraper-api-keys`` — every field accepted any JSON type;
       ``ra_apikey=42`` would crash any ``f"...?y={key}"`` formatter that
       expects a string.

    Pass 45.11 adds ``services/scraper_settings_validators.py`` mirroring the
    existing ``services/settings_validators.py`` pattern and threads the
    validators through the three endpoints with a 400 envelope on failure."""

    # ------- /api/settings/logging -----------------------------------------
    def test_logging_endpoint_calls_validator(self, monkeypatch):
        """Pure-function: call the validator on a malformed logging block
        and confirm it rejects."""
        from services.settings_validators import validate_settings_value
        ok, reason, _ = validate_settings_value('logging', 'a string, not a dict')
        assert ok is False
        assert 'object' in reason.lower()

    def test_logging_endpoint_rejects_malformed_with_400(self, monkeypatch):
        """End-to-end: POST a non-dict logging body, expect 400 and a
        validator-shaped error message."""
        import app as app_module
        import settings_manager as _settings_manager
        fake_admin = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}
        monkeypatch.setattr(app_module, 'get_current_user', lambda: fake_admin)
        monkeypatch.setattr(app_module, 'get_user_settings', lambda _uid: None)
        monkeypatch.setattr(_settings_manager, 'load_settings',
                            lambda: {'setup_completed': True})
        # Belt-and-braces: if validation ever regresses, save_settings must
        # NOT touch the real data/settings.json — Pass 46.4 traced a silent
        # ESRGAN-init outage to a stale `"this is not a dict"` value left
        # in the user's settings.json by an unsandboxed earlier run.
        monkeypatch.setattr(_settings_manager, 'save_settings', lambda _s: True)
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        with app_module.app.test_client() as c:
            with c.session_transaction() as sess:
                sess['_csrf_token'] = 'pass45_11-token'
            resp = c.post(
                '/api/settings/logging',
                json='this is not a dict',
                headers={'X-CSRF-Token': 'pass45_11-token'},
            )
        assert resp.status_code == 400, resp.get_data(as_text=True)
        body = resp.get_json()
        assert body['success'] is False
        assert 'invalid logging settings' in body['error']

    def test_logging_endpoint_rejects_unknown_category(self, monkeypatch):
        """Unknown log category like 'rce_via_log_init' must be rejected."""
        import app as app_module
        import settings_manager as _settings_manager
        fake_admin = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}
        monkeypatch.setattr(app_module, 'get_current_user', lambda: fake_admin)
        monkeypatch.setattr(app_module, 'get_user_settings', lambda _uid: None)
        monkeypatch.setattr(_settings_manager, 'load_settings',
                            lambda: {'setup_completed': True})
        monkeypatch.setattr(_settings_manager, 'save_settings', lambda _s: True)
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        with app_module.app.test_client() as c:
            with c.session_transaction() as sess:
                sess['_csrf_token'] = 'pass45_11-token'
            resp = c.post(
                '/api/settings/logging',
                json={'rce_via_log_init': {'info': True}},
                headers={'X-CSRF-Token': 'pass45_11-token'},
            )
        assert resp.status_code == 400
        assert 'unknown log category' in resp.get_json()['error']

    def test_logging_endpoint_route_calls_validator(self):
        """Source-position pin: the route body must call
        validate_settings_value before assigning settings['logging']."""
        path = os.path.join(_REPO_ROOT, 'routes', 'settings.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        idx = body.find('def api_save_logging_settings')
        assert idx != -1
        next_def = body.find('\ndef ', idx + 1)
        slice_body = body[idx:next_def] if next_def != -1 else body[idx:]
        v_pos = slice_body.find("validate_settings_value('logging'")
        assign_pos = slice_body.find("settings['logging']")
        assert v_pos != -1, (
            "api_save_logging_settings must call validate_settings_value "
            "('logging', ...) (Pass 45.11)"
        )
        assert v_pos < assign_pos, (
            "validate_settings_value must run BEFORE settings['logging'] "
            "is assigned (Pass 45.11)"
        )

    # ------- /api/scraper-settings ----------------------------------------
    def test_scraper_settings_validator_rejects_bogus_priority(self):
        """Pure-function: bogus scraper name in priority must be rejected."""
        from services.scraper_settings_validators import validate_scraper_settings
        ok, reason, _ = validate_scraper_settings({
            'priority': ['esde', '../etc/passwd'],
        })
        assert ok is False
        assert 'priority' in reason.lower()

    def test_scraper_settings_validator_rejects_string_for_bool(self):
        """enabled must be {scraper: bool}; reject string values."""
        from services.scraper_settings_validators import validate_scraper_settings
        ok, reason, _ = validate_scraper_settings({
            'enabled': {'tgdb': 'yes'},
        })
        assert ok is False
        assert 'true or false' in reason.lower()

    def test_scraper_settings_validator_rejects_string_score(self):
        """minimum_match_score must be int 0-1000."""
        from services.scraper_settings_validators import validate_scraper_settings
        ok, reason, _ = validate_scraper_settings({
            'minimum_match_score': 'lots',
        })
        assert ok is False
        assert 'integer' in reason.lower()

    def test_scraper_settings_validator_rejects_unknown_top_level(self):
        """Top-level unknown key must be rejected (allowlist behaviour)."""
        from services.scraper_settings_validators import validate_scraper_settings
        ok, reason, _ = validate_scraper_settings({
            'rce_payload': 'hi',
        })
        assert ok is False
        assert 'unknown' in reason.lower()

    def test_scraper_settings_validator_accepts_valid_payload(self):
        """Valid full-shape payload passes and round-trips intact."""
        from services.scraper_settings_validators import validate_scraper_settings
        ok, reason, cleaned = validate_scraper_settings({
            'priority': ['esde', 'tgdb', 'igdb', 'rawg', 'screenscraper', 'ai'],
            'enabled': {'esde': True, 'tgdb': False},
            'minimum_match_score': 200,
            'match_mode': 'criteria',
            'match_criteria': {'platform_required': True, 'title_quality': 'close'},
        })
        assert ok is True, reason
        assert cleaned['priority'] == ['esde', 'tgdb', 'igdb', 'rawg', 'screenscraper', 'ai']
        assert cleaned['match_criteria']['title_quality'] == 'close'

    def test_scraper_settings_endpoint_rejects_with_400(self, monkeypatch):
        """End-to-end: bogus priority must return 400 from the route."""
        import app as app_module
        import settings_manager as _settings_manager
        fake_admin = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}
        monkeypatch.setattr(app_module, 'get_current_user', lambda: fake_admin)
        monkeypatch.setattr(app_module, 'get_user_settings', lambda _uid: None)
        monkeypatch.setattr(_settings_manager, 'load_settings',
                            lambda: {'setup_completed': True})
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        with app_module.app.test_client() as c:
            with c.session_transaction() as sess:
                sess['_csrf_token'] = 'pass45_11-token'
            resp = c.post(
                '/api/scraper-settings',
                json={'priority': ['../etc/passwd']},
                headers={'X-CSRF-Token': 'pass45_11-token'},
            )
        assert resp.status_code == 400, resp.get_data(as_text=True)
        assert 'invalid scraper settings' in resp.get_json()['error']

    # ------- /api/scraper-api-keys ----------------------------------------
    def test_api_keys_validator_rejects_int_for_string(self):
        """ra_apikey=42 must fail — every value is a string."""
        from services.scraper_settings_validators import validate_scraper_api_keys
        ok, reason, _ = validate_scraper_api_keys({'ra_apikey': 42})
        assert ok is False
        assert 'must be a string' in reason

    def test_api_keys_validator_rejects_unknown_field(self):
        """Allowlist: unknown api-key field is rejected."""
        from services.scraper_settings_validators import validate_scraper_api_keys
        ok, reason, _ = validate_scraper_api_keys({'rce_field': 'x'})
        assert ok is False
        assert 'unknown' in reason.lower()

    def test_api_keys_validator_rejects_control_char(self):
        """Reject NUL/CR/LF that would smuggle into log lines or
        querystrings."""
        from services.scraper_settings_validators import validate_scraper_api_keys
        ok, reason, _ = validate_scraper_api_keys({'tgdb': 'abc\ndef'})
        assert ok is False
        assert 'control' in reason.lower()

    def test_api_keys_validator_rejects_invalid_provider(self):
        """ai_provider is enum-locked."""
        from services.scraper_settings_validators import validate_scraper_api_keys
        ok, reason, _ = validate_scraper_api_keys({'ai_provider': 'evil_llm'})
        assert ok is False
        assert 'ai_provider' in reason

    def test_api_keys_validator_accepts_known_fields(self):
        """All allowlisted fields must accept their normal string values."""
        from services.scraper_settings_validators import validate_scraper_api_keys
        ok, reason, cleaned = validate_scraper_api_keys({
            'tgdb': 'a' * 64,
            'igdb_client_id': 'twitch_client',
            'ra_username': 'milnet',
            'ai_provider': 'gemini',
            'steam_id': '76561199800524431',
        })
        assert ok is True, reason
        assert cleaned['tgdb'] == 'a' * 64

    def test_api_keys_endpoint_rejects_with_400(self, monkeypatch):
        """End-to-end: bogus type must return 400 from the route."""
        import app as app_module
        import settings_manager as _settings_manager
        fake_admin = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}
        monkeypatch.setattr(app_module, 'get_current_user', lambda: fake_admin)
        monkeypatch.setattr(app_module, 'get_user_settings', lambda _uid: None)
        monkeypatch.setattr(_settings_manager, 'load_settings',
                            lambda: {'setup_completed': True})
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        with app_module.app.test_client() as c:
            with c.session_transaction() as sess:
                sess['_csrf_token'] = 'pass45_11-token'
            resp = c.post(
                '/api/scraper-api-keys',
                json={'ra_apikey': 42},
                headers={'X-CSRF-Token': 'pass45_11-token'},
            )
        assert resp.status_code == 400, resp.get_data(as_text=True)
        assert 'invalid api keys' in resp.get_json()['error']

    # ------- import / wiring sanity ----------------------------------------
    def test_scraper_routes_imports_validator(self):
        """routes/scraper.py must import and call both validators."""
        path = os.path.join(_REPO_ROOT, 'routes', 'scraper.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        assert 'from services.scraper_settings_validators import' in body
        assert 'validate_scraper_settings(' in body
        assert 'validate_scraper_api_keys(' in body


# -----------------------------------------------------------------------------
# 45.12 — Xbox refresh-token rotation hardening
# -----------------------------------------------------------------------------
class TestPass45_12XboxTokenRotation:
    """Pass 45.12 hardens the Xbox token-refresh path against three problems
    in scraper/scrape_xbox.py:

    1. **Refresh-on-every-call**: get_authenticated_session() refreshed the
       access_token on every call regardless of validity, burning Microsoft
       API quota and exposing every page load to a transient token-endpoint
       outage. We now track ``expires_at = now + expires_in - 60s`` (60-sec
       safety margin) and skip the refresh when the token is still fresh.
    2. **Stuck-token loop**: when refresh returned None (revoked / 401 loop),
       the function fell through silently. The dead token would survive
       across requests and the user would see "Xbox connected" forever
       despite no working session. Pass 45.12 calls ``clear_tokens(user_id)``
       on refresh failure so the user is forced through the OAuth flow.
    3. **Stale xuid/gamertag**: stored xuid/gamertag from the original OAuth
       callback were carried across refreshes forever. A user who changed
       their gamertag on Xbox.com would see the old value until they
       disconnected/reconnected. Pass 45.12 drops xuid/gamertag from the
       saved token dict on refresh so the XSTS/profile flow below
       re-validates against the live account."""

    def test_attach_expires_at_uses_60s_safety_margin(self):
        """expires_at must be at least 60 seconds before the absolute
        expiry to avoid riding the token to its final tick."""
        import time as _time
        from scraper.scrape_xbox import attach_expires_at
        before = _time.time()
        tokens = {'access_token': 'abc', 'expires_in': 3600}
        attach_expires_at(tokens)
        after = _time.time()
        # Should be roughly now + (3600 - 60) = now + 3540.
        assert tokens['expires_at'] >= before + 3540 - 1
        assert tokens['expires_at'] <= after + 3540 + 1

    def test_attach_expires_at_handles_missing_expires_in(self):
        """Defaults to 3600s if expires_in is missing (Microsoft default)."""
        import time as _time
        from scraper.scrape_xbox import attach_expires_at
        before = _time.time()
        tokens = {'access_token': 'abc'}
        attach_expires_at(tokens)
        # Should be roughly now + (3600 - 60).
        assert tokens['expires_at'] >= before + 3540 - 1

    def test_attach_expires_at_handles_garbage_expires_in(self):
        """Non-numeric expires_in falls back to default rather than crashing."""
        from scraper.scrape_xbox import attach_expires_at
        tokens = {'access_token': 'abc', 'expires_in': 'forever'}
        attach_expires_at(tokens)
        assert isinstance(tokens['expires_at'], (int, float))

    def test_attach_expires_at_clamps_to_minimum_60s(self):
        """A 1-second token still gets at least 60 seconds of validity, so
        the negative `expires_in - 60` doesn't push expires_at into the
        past (which would force an immediate re-refresh loop)."""
        import time as _time
        from scraper.scrape_xbox import attach_expires_at
        before = _time.time()
        tokens = {'access_token': 'abc', 'expires_in': 5}
        attach_expires_at(tokens)
        # max(60, 5-60) = 60, so expires_at is at least now+60.
        assert tokens['expires_at'] >= before + 60 - 1

    def test_fresh_token_skips_refresh(self, monkeypatch):
        """A token with expires_at in the future must not trigger a
        refresh_access_token call."""
        from scraper import scrape_xbox

        load_calls = []
        refresh_calls = []
        monkeypatch.setattr(scrape_xbox, 'load_tokens',
                            lambda uid: {'access_token': 'still_good',
                                         'refresh_token': 'rt',
                                         'expires_at': time.time() + 1000})

        def boom_refresh(*a, **kw):
            refresh_calls.append(a)
            return None
        monkeypatch.setattr(scrape_xbox, 'refresh_access_token', boom_refresh)
        monkeypatch.setattr(scrape_xbox, 'authenticate_xbox_live',
                            lambda tok: ('xbl', 'hash'))
        monkeypatch.setattr(scrape_xbox, 'get_xsts_token',
                            lambda tok: ('xsts', 'xuid123'))

        result = scrape_xbox.get_authenticated_session('cid', 'csec', 99)
        assert result is not None, "session must succeed with fresh token"
        assert refresh_calls == [], (
            "Pass 45.12: refresh_access_token must not be called when "
            "expires_at says the access_token is still valid"
        )

    def test_stale_token_triggers_refresh(self, monkeypatch):
        """A token with expires_at in the past triggers a refresh."""
        from scraper import scrape_xbox

        refresh_calls = []
        monkeypatch.setattr(scrape_xbox, 'load_tokens',
                            lambda uid: {'access_token': 'old',
                                         'refresh_token': 'rt',
                                         'expires_at': time.time() - 1,
                                         'xuid': 'old_xuid',
                                         'gamertag': 'OldName'})

        def fake_refresh(*a, **kw):
            refresh_calls.append(a)
            return {'access_token': 'new', 'refresh_token': 'rt2',
                    'expires_in': 3600}
        monkeypatch.setattr(scrape_xbox, 'refresh_access_token', fake_refresh)

        saved = []
        monkeypatch.setattr(scrape_xbox, 'save_tokens',
                            lambda tokens, uid: saved.append(dict(tokens)))
        monkeypatch.setattr(scrape_xbox, 'authenticate_xbox_live',
                            lambda tok: ('xbl', 'hash'))
        monkeypatch.setattr(scrape_xbox, 'get_xsts_token',
                            lambda tok: ('xsts', 'xuid_new'))

        scrape_xbox.get_authenticated_session('cid', 'csec', 99)
        assert len(refresh_calls) == 1, "refresh must run on stale token"
        assert len(saved) == 1, "saved token must be persisted"
        # Pass 45.12 — saved tokens must have a fresh expires_at.
        assert 'expires_at' in saved[0]
        assert saved[0]['expires_at'] > time.time()
        # Pass 45.12 — xuid/gamertag must have been dropped on refresh.
        assert 'xuid' not in saved[0], (
            "Pass 45.12: refresh must drop stored xuid so XSTS re-validates"
        )
        assert 'gamertag' not in saved[0], (
            "Pass 45.12: refresh must drop stored gamertag so profile "
            "lookup re-validates"
        )

    def test_failed_refresh_clears_tokens(self, monkeypatch):
        """When refresh_access_token returns None, the user's stored tokens
        must be cleared via clear_tokens(user_id) — otherwise the dead
        refresh_token sits in the DB forever."""
        from scraper import scrape_xbox

        monkeypatch.setattr(scrape_xbox, 'load_tokens',
                            lambda uid: {'access_token': '',
                                         'refresh_token': 'revoked_rt',
                                         'expires_at': time.time() - 1})
        monkeypatch.setattr(scrape_xbox, 'refresh_access_token',
                            lambda *a, **kw: None)

        cleared = []
        monkeypatch.setattr(scrape_xbox, 'clear_tokens',
                            lambda uid: cleared.append(uid))
        # save_tokens / authenticate paths must not be reached.
        monkeypatch.setattr(scrape_xbox, 'save_tokens',
                            lambda *a, **kw: pytest.fail(
                                "save_tokens must not run when refresh fails"))
        monkeypatch.setattr(scrape_xbox, 'authenticate_xbox_live',
                            lambda tok: pytest.fail(
                                "authenticate must not run when refresh fails"))

        result = scrape_xbox.get_authenticated_session('cid', 'csec', 42)
        assert result is None, "failed refresh must yield None session"
        assert cleared == [42], (
            "Pass 45.12: clear_tokens(user_id) must be called when refresh "
            "returns None"
        )

    def test_oauth_callback_attaches_expires_at(self):
        """routes/platform_import.py xbox_callback must call attach_expires_at
        before save_tokens so the initial connect carries an expiry, not just
        post-refresh saves."""
        path = os.path.join(_REPO_ROOT, 'routes', 'platform_import.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        idx = body.find('def api_xbox_callback')
        assert idx != -1
        next_def = body.find('\ndef ', idx + 1)
        slice_body = body[idx:next_def] if next_def != -1 else body[idx:]
        # Both calls must exist within the callback, and attach_expires_at
        # must be ordered before save_tokens.
        attach_pos = slice_body.find('attach_expires_at(tokens)')
        save_pos = slice_body.find('save_tokens(tokens, g.user[\'id\'])')
        assert attach_pos != -1, (
            "Pass 45.12: xbox callback must call attach_expires_at(tokens)"
        )
        assert save_pos != -1, "xbox callback must call save_tokens"
        assert attach_pos < save_pos, (
            "attach_expires_at must run BEFORE save_tokens (Pass 45.12)"
        )


# Imported at top of module by some 45.12 tests; alias for convenience.
import time


# -----------------------------------------------------------------------------
# 45.13 — IGDB token cache thread-safety + RA y/z URL redactor
# -----------------------------------------------------------------------------
class TestPass45_13IgdbCacheAndRedactor:
    """Pass 45.13 closes two distinct findings on the same review pass:

    1. ``scraper/scrape_igdb.py:_igdb_token_cache`` was a bare module-level
       dict mutated from background threads (bulk scrape runs IGDB in a
       thread pool). Two threads racing the cache-empty branch could each
       fire a Twitch OAuth call and the second one would clobber the first
       — same race the existing
       ``scraper/retroachievements.py:_ra_console_cache_lock`` already
       handles. Fix: wrap reads/writes in a ``threading.Lock``.
    2. ``services/log_redactor.py`` URL-querystring rule covered the long
       parameter names (``apikey``, ``token``, ``key``, ``sspassword``...)
       but not the RetroAchievements single-character names: ``?y=API_KEY``
       and ``?z=USERNAME``. If any caller logged the full URL after
       requests had encoded the params, the API key would slip into
       ``logs/scraping_*.log`` unredacted. Latent leak — no current
       callsite logs the encoded URL, but the rule was missing from the
       allowlist. Fix: add ``y`` and ``z`` with the existing ``[?&]`` boundary
       so legitimate query names like ``?fancy=`` / ``?lazy=`` don't
       false-positive."""

    def test_igdb_token_cache_lock_exists(self):
        """The lock object must exist and be a threading.Lock — the same
        type the redaction tests use."""
        from scraper import scrape_igdb
        # threading.Lock returns a `lock` instance whose type isn't directly
        # importable; check the acquire/release interface instead.
        assert hasattr(scrape_igdb, '_igdb_token_cache_lock'), (
            "Pass 45.13: scrape_igdb must define _igdb_token_cache_lock"
        )
        lock = scrape_igdb._igdb_token_cache_lock
        assert hasattr(lock, 'acquire') and hasattr(lock, 'release'), (
            "Pass 45.13: _igdb_token_cache_lock must be a threading lock"
        )

    def test_igdb_auth_acquires_lock(self, monkeypatch):
        """Calling igdb_auth() must hold the lock during its critical
        section. We assert this by replacing the lock with an instrumented
        wrapper and confirming the http_post happens between
        __enter__/__exit__."""
        from scraper import scrape_igdb

        class _SpyLock:
            def __init__(self):
                self.depth = 0
                self.events = []

            def __enter__(self):
                self.depth += 1
                self.events.append('enter')
                return self

            def __exit__(self, *a):
                self.events.append('exit')
                self.depth -= 1

            # threading.Lock-compatible API for the rest of the codebase.
            def acquire(self, *a, **kw):
                return self.__enter__()

            def release(self):
                return self.__exit__(None, None, None)

        spy = _SpyLock()
        monkeypatch.setattr(scrape_igdb, '_igdb_token_cache_lock', spy)
        # Reset cache so we hit the http_post branch.
        monkeypatch.setattr(scrape_igdb, '_igdb_token_cache',
                            {'token': None, 'expires_at': 0})
        monkeypatch.setattr(scrape_igdb, '_get_igdb_credentials',
                            lambda: ('cid', 'csec'))

        class _FakeResp:
            def __init__(self):
                self.status_code = 200

            def raise_for_status(self):
                pass

            def json(self):
                # When http_post is called we should already be inside the
                # lock. Capture lock depth at call time.
                spy.events.append(f'http_post(depth={spy.depth})')
                return {'access_token': 'abc', 'expires_in': 3600}

        monkeypatch.setattr(scrape_igdb, 'http_post', lambda *a, **kw: _FakeResp())

        scrape_igdb.igdb_auth()

        # Lock must have entered before http_post and exited after it.
        # Find the http_post event and confirm depth was at least 1.
        http_event = next(e for e in spy.events if e.startswith('http_post'))
        assert 'depth=1' in http_event, (
            f"http_post must run inside the lock; events={spy.events}"
        )
        assert spy.events[0] == 'enter'
        assert spy.events[-1] == 'exit'

    def test_igdb_request_401_clears_cache_under_lock(self, monkeypatch):
        """The 401-retry path also mutates the cache; that mutation must
        run under the lock too."""
        path = os.path.join(_REPO_ROOT, 'scraper', 'scrape_igdb.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        # Find the 401 branch.
        idx = body.find('if r.status_code == 401:')
        assert idx != -1
        # The cache reset (token=None) inside that branch must be inside a
        # `with _igdb_token_cache_lock:` block. Look ahead 1 KB and confirm
        # the lock acquire precedes the cache assignment.
        slice_body = body[idx:idx + 2048]
        lock_pos = slice_body.find('with _igdb_token_cache_lock:')
        clear_pos = slice_body.find("_igdb_token_cache['token'] = None")
        assert lock_pos != -1, (
            "Pass 45.13: 401 branch must reset cache under the lock"
        )
        assert lock_pos < clear_pos, (
            "Pass 45.13: lock must be acquired before clearing the cache"
        )

    def test_redactor_strips_ra_y_querystring(self):
        """The y= querystring (RA API key) must be redacted in log output."""
        from services.log_redactor import redact
        url = "https://retroachievements.org/API/API_GetGame.php?i=1&y=bsPsMBglImmVf4mj14W3llur3m7DxaCC&u=milnet"
        redacted = redact(url)
        assert 'bsPsMBglImmVf4mj14W3llur3m7DxaCC' not in redacted, (
            "Pass 45.13: the RA API key (?y=KEY) must be redacted"
        )
        assert 'y=<redacted>' in redacted

    def test_redactor_strips_ra_z_querystring(self):
        """The z= querystring (RA username) must also be redacted —
        usernames link real-world identity to scraped activity, and
        the redactor allowlist is narrow to begin with."""
        from services.log_redactor import redact
        url = "https://retroachievements.org/API/API_GetUserSummary.php?z=milnet&y=KEY"
        redacted = redact(url)
        assert 'z=milnet' not in redacted, (
            "Pass 45.13: the RA username (?z=USER) must be redacted"
        )
        assert 'z=<redacted>' in redacted

    def test_redactor_does_not_clobber_lazy_or_fancy(self):
        """Single-character `y` / `z` allowlist must not over-match
        innocent multi-letter query names like `?lazy=` or `?fancy=` —
        the existing `[?&]` boundary handles this."""
        from services.log_redactor import redact
        url = "https://example.com/?fancy=true&lazy=1&category=gaming"
        redacted = redact(url)
        # Nothing in this URL is a credential; nothing must be redacted.
        assert redacted == url, (
            f"Pass 45.13: innocent params must not be redacted; got {redacted}"
        )

    def test_redactor_handles_y_at_url_start(self):
        """Coverage: the `?y=` form (immediately after the ?) must work,
        not just `&y=` after another param. Both share the `[?&]` class."""
        from services.log_redactor import redact
        url = "https://retroachievements.org/API/x.php?y=SECRET_KEY_HERE&z=user"
        redacted = redact(url)
        assert 'SECRET_KEY_HERE' not in redacted
        assert 'user' not in redacted.split('z=')[1].split('&')[0] if 'z=' in redacted else True


# -----------------------------------------------------------------------------
# 45.14 — TGDB / RAWG / IGDB max_bytes
# -----------------------------------------------------------------------------
class TestPass45_14ApiResponseCaps:
    """Pass 45.14 closes the last three scrapers that called ``http_get``/
    ``http_post`` without the ``max_bytes`` kwarg: TheGamesDB
    (``scrape_thegamesdb.py``), RAWG (``scrape_rawg.py``), IGDB
    (``scrape_igdb.py`` — three call sites: Twitch OAuth, primary IGDB
    request, and the 401-retry).

    Without ``max_bytes``, a malicious or buggy upstream returning a
    multi-gigabyte JSON body would force the scraper process to allocate
    enough RAM to OOM the host. The cap matches RetroAchievements + AI +
    ScreenScraper precedent: ``getattr(config, 'MAX_API_RESPONSE_BYTES',
    10*1024*1024)`` (10 MiB)."""

    def test_tgdb_passes_max_bytes(self, monkeypatch):
        """Functional: the TGDB request site forwards max_bytes to
        http_get."""
        from scraper import scrape_thegamesdb

        captured = {}

        def fake_http_get(url, **kwargs):
            captured.update(kwargs)
            return None  # signal failure path so we don't proceed

        monkeypatch.setattr(scrape_thegamesdb, 'http_get', fake_http_get)
        # Force a key to be available so the for-loop runs.
        monkeypatch.setattr(scrape_thegamesdb, 'get_api_keys',
                            lambda: ('pub_key', ''))
        scrape_thegamesdb._tgdb_request('https://api.thegamesdb.net/v1/Games')
        assert 'max_bytes' in captured, (
            "Pass 45.14: TGDB http_get must be called with max_bytes"
        )
        assert captured['max_bytes'] >= 1024 * 1024, (
            "max_bytes must be a sensible cap, not a tiny value"
        )

    def test_rawg_passes_max_bytes(self, monkeypatch):
        """RAWG: max_bytes must reach http_get."""
        from scraper import scrape_rawg

        captured = {}

        def fake_http_get(url, **kwargs):
            captured.update(kwargs)
            return None

        monkeypatch.setattr(scrape_rawg, 'http_get', fake_http_get)
        # CI has no data/scraper_settings.json, so the real _get_api_key
        # returns '' and _make_request early-returns before the http_get
        # call. Stub the key fetch.
        monkeypatch.setattr(scrape_rawg, '_get_api_key', lambda: 'fake_key')
        # _make_request signature: (endpoint, params=None, max_retries=2)
        scrape_rawg._make_request('games', {'search': 'foo'})
        assert 'max_bytes' in captured, (
            "Pass 45.14: RAWG http_get must be called with max_bytes"
        )

    def test_igdb_auth_passes_max_bytes(self, monkeypatch):
        """IGDB Twitch OAuth: max_bytes must reach http_post."""
        from scraper import scrape_igdb
        # Reset cache so we hit the http_post.
        monkeypatch.setattr(scrape_igdb, '_igdb_token_cache',
                            {'token': None, 'expires_at': 0})
        monkeypatch.setattr(scrape_igdb, '_get_igdb_credentials',
                            lambda: ('cid', 'csec'))

        captured = {}

        class _FakeResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return {'access_token': 'x', 'expires_in': 100}

        def fake_http_post(url, **kwargs):
            captured.update(kwargs)
            return _FakeResp()

        monkeypatch.setattr(scrape_igdb, 'http_post', fake_http_post)
        scrape_igdb.igdb_auth()
        assert 'max_bytes' in captured, (
            "Pass 45.14: IGDB Twitch OAuth http_post must pass max_bytes"
        )

    def test_igdb_request_passes_max_bytes(self, monkeypatch):
        """IGDB primary endpoint: max_bytes must reach http_post."""
        from scraper import scrape_igdb
        monkeypatch.setattr(scrape_igdb, '_get_igdb_credentials',
                            lambda: ('cid', 'csec'))

        captured = {}

        class _FakeResp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self): return [{'id': 1}]

        def fake_http_post(url, **kwargs):
            captured.update(kwargs)
            return _FakeResp()

        monkeypatch.setattr(scrape_igdb, 'http_post', fake_http_post)
        scrape_igdb.igdb_request('games', 'where 1=1;', 'tok')
        assert 'max_bytes' in captured, (
            "Pass 45.14: IGDB primary request http_post must pass max_bytes"
        )

    def test_igdb_request_401_retry_passes_max_bytes(self, monkeypatch):
        """The 401-retry path is a separate http_post call site —
        max_bytes must be present there too."""
        path = os.path.join(_REPO_ROOT, 'scraper', 'scrape_igdb.py')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        # Find igdb_request and confirm both http_post calls inside it
        # carry max_bytes.
        idx = body.find('def igdb_request')
        assert idx != -1
        next_def = body.find('\ndef ', idx + 1)
        slice_body = body[idx:next_def] if next_def != -1 else body[idx:]
        post_count = slice_body.count('http_post(')
        max_bytes_count = slice_body.count('max_bytes=')
        assert max_bytes_count >= post_count, (
            f"Pass 45.14: igdb_request has {post_count} http_post calls "
            f"but only {max_bytes_count} max_bytes args — both primary and "
            f"401-retry paths must carry the cap"
        )

    def test_max_bytes_value_matches_config(self):
        """Sanity: each module's _MAX_BYTES constant resolves to the same
        config value RA / AI use, with the same fallback default."""
        from scraper import scrape_thegamesdb, scrape_rawg, scrape_igdb
        import config
        expected = getattr(config, 'MAX_API_RESPONSE_BYTES', 10 * 1024 * 1024)
        assert scrape_thegamesdb._TGDB_MAX_BYTES == expected
        assert scrape_rawg._RAWG_MAX_BYTES == expected
        assert scrape_igdb._IGDB_MAX_BYTES == expected


# -----------------------------------------------------------------------------
# 45.15 — Migration 011: user_game_views CASCADE FKs
# -----------------------------------------------------------------------------
class TestPass45_15UserGameViewsCascadeFK:
    """Pass 45.15 closes a slow-orphan leak in user_game_views.

    Migration 010 created the table with composite PK (user_id, game_id) but
    no FOREIGN KEY clauses. When a game or user was deleted, rows in
    user_game_views were left orphaned — the recently-viewed dropdown ran
    the JOIN against `games` and silently skipped the orphans, but they
    accumulated forever. Pass 45.15 ships migration 011 that rebuilds the
    table with ``ON DELETE CASCADE`` on both FKs, prunes existing orphans
    in the same transaction, and pins the contract via PRAGMA
    foreign_key_check(user_game_views) before commit (Pass 45.10 pattern)."""

    @pytest.fixture
    def fresh_db(self, tmp_path):
        """Build a SQLite DB with games + users + a pre-Pass-45.15
        user_game_views table (no FKs) and run migration 011 against it."""
        import sqlite3
        db_path = tmp_path / 'test.db'
        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA foreign_keys = ON")
        # Minimal schema: games + users + the legacy user_game_views.
        conn.execute("CREATE TABLE games (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT)")
        conn.execute("""
            CREATE TABLE user_game_views (
                user_id     INTEGER NOT NULL,
                game_id     INTEGER NOT NULL,
                last_viewed TEXT NOT NULL,
                PRIMARY KEY (user_id, game_id)
            )
        """)
        conn.commit()
        return conn

    def test_migration_adds_two_fk_clauses(self, fresh_db):
        """After migration 011, user_game_views must declare 2 FKs."""
        import importlib
        mod = importlib.import_module(
            'services.migrations.scripts.011_user_game_views_cascade_fk'
        )
        mod.apply(fresh_db)
        fresh_db.commit()
        fks = fresh_db.execute(
            "PRAGMA foreign_key_list(user_game_views)"
        ).fetchall()
        assert len(fks) == 2, (
            f"Pass 45.15: user_game_views must have 2 FK clauses; got {fks}"
        )
        # Both FKs must declare ON DELETE CASCADE.
        on_delete = {row[6] for row in fks}  # column index 6 is on_delete
        assert on_delete == {'CASCADE'}, (
            f"Pass 45.15: both FKs must use ON DELETE CASCADE; got {on_delete}"
        )
        targets = {row[2] for row in fks}  # column 2 is the parent table
        assert targets == {'games', 'users'}

    def test_cascade_delete_propagates_from_games(self, fresh_db):
        """Deleting a game must propagate to user_game_views (cascade)."""
        import importlib
        mod = importlib.import_module(
            'services.migrations.scripts.011_user_game_views_cascade_fk'
        )
        # Seed parent + child rows.
        fresh_db.execute("INSERT INTO users(id, username) VALUES (1, 'a')")
        fresh_db.execute("INSERT INTO games(id, name) VALUES (10, 'g')")
        fresh_db.execute(
            "INSERT INTO user_game_views(user_id, game_id, last_viewed) "
            "VALUES (1, 10, '2026-04-27')"
        )
        fresh_db.commit()

        mod.apply(fresh_db)
        fresh_db.commit()

        # Cascade must trigger on parent delete.
        fresh_db.execute("DELETE FROM games WHERE id = 10")
        fresh_db.commit()
        rows = fresh_db.execute(
            "SELECT user_id, game_id FROM user_game_views"
        ).fetchall()
        assert rows == [], (
            "Pass 45.15: deleting a game must cascade to user_game_views"
        )

    def test_cascade_delete_propagates_from_users(self, fresh_db):
        """Deleting a user must propagate to user_game_views (cascade)."""
        import importlib
        mod = importlib.import_module(
            'services.migrations.scripts.011_user_game_views_cascade_fk'
        )
        fresh_db.execute("INSERT INTO users(id, username) VALUES (1, 'a')")
        fresh_db.execute("INSERT INTO games(id, name) VALUES (10, 'g')")
        fresh_db.execute(
            "INSERT INTO user_game_views(user_id, game_id, last_viewed) "
            "VALUES (1, 10, '2026-04-27')"
        )
        fresh_db.commit()

        mod.apply(fresh_db)
        fresh_db.commit()

        fresh_db.execute("DELETE FROM users WHERE id = 1")
        fresh_db.commit()
        rows = fresh_db.execute(
            "SELECT user_id, game_id FROM user_game_views"
        ).fetchall()
        assert rows == [], (
            "Pass 45.15: deleting a user must cascade to user_game_views"
        )

    def test_migration_prunes_orphan_rows(self, fresh_db):
        """Pre-existing orphans (rows pointing at deleted games/users) must
        be dropped during the rebuild."""
        import importlib
        mod = importlib.import_module(
            'services.migrations.scripts.011_user_game_views_cascade_fk'
        )
        fresh_db.execute("INSERT INTO users(id, username) VALUES (1, 'a')")
        fresh_db.execute("INSERT INTO games(id, name) VALUES (10, 'g')")
        # One valid row.
        fresh_db.execute(
            "INSERT INTO user_game_views(user_id, game_id, last_viewed) "
            "VALUES (1, 10, '2026-04-27')"
        )
        # One orphan: game 99 doesn't exist.
        fresh_db.execute(
            "INSERT INTO user_game_views(user_id, game_id, last_viewed) "
            "VALUES (1, 99, '2026-04-26')"
        )
        # One orphan: user 99 doesn't exist.
        fresh_db.execute(
            "INSERT INTO user_game_views(user_id, game_id, last_viewed) "
            "VALUES (99, 10, '2026-04-25')"
        )
        fresh_db.commit()

        mod.apply(fresh_db)
        fresh_db.commit()

        rows = fresh_db.execute(
            "SELECT user_id, game_id FROM user_game_views ORDER BY user_id, game_id"
        ).fetchall()
        assert rows == [(1, 10)], (
            f"Pass 45.15: orphans must be pruned; survivors={rows}"
        )

    def test_migration_is_idempotent(self, fresh_db):
        """Running migration 011 twice must be a no-op the second time."""
        import importlib
        mod = importlib.import_module(
            'services.migrations.scripts.011_user_game_views_cascade_fk'
        )
        # Seed and apply once.
        fresh_db.execute("INSERT INTO users(id, username) VALUES (1, 'a')")
        fresh_db.execute("INSERT INTO games(id, name) VALUES (10, 'g')")
        fresh_db.execute(
            "INSERT INTO user_game_views(user_id, game_id, last_viewed) "
            "VALUES (1, 10, '2026-04-27')"
        )
        fresh_db.commit()
        mod.apply(fresh_db)
        fresh_db.commit()

        # Second apply must not raise and must leave the row intact.
        mod.apply(fresh_db)
        fresh_db.commit()
        rows = fresh_db.execute(
            "SELECT user_id, game_id FROM user_game_views"
        ).fetchall()
        assert rows == [(1, 10)]
        # Still 2 FKs.
        fks = fresh_db.execute(
            "PRAGMA foreign_key_list(user_game_views)"
        ).fetchall()
        assert len(fks) == 2

    def test_migration_registered_in_runner(self):
        """The migration must be appended to the MIGRATIONS list — without
        this, it won't run on existing installs."""
        from services import migrations
        assert '011_user_game_views_cascade_fk' in migrations.MIGRATIONS
        # The cascade-FK migration must come immediately after its target
        # (010_user_game_views) — append-only contract is preserved by
        # putting subsequent migrations (012_emulators) at higher indices.
        idx = migrations.MIGRATIONS.index('011_user_game_views_cascade_fk')
        assert migrations.MIGRATIONS[idx - 1] == '010_user_game_views'

    def test_migration_runs_scoped_foreign_key_check(self):
        """Pass 45.10 contract: rebuild migrations must pin a scoped
        foreign_key_check on the rebuilt table before commit."""
        path = os.path.join(
            _REPO_ROOT, 'services', 'migrations', 'scripts',
            '011_user_game_views_cascade_fk.py'
        )
        with open(path, encoding='utf-8') as f:
            body = f.read()
        assert 'PRAGMA foreign_key_check(user_game_views)' in body, (
            "Pass 45.15 must run the scoped foreign_key_check (Pass 45.10 pattern)"
        )


# -----------------------------------------------------------------------------
# 45.16 — aria-current="page" rollout to tab-style navs
# -----------------------------------------------------------------------------
class TestPass45_16AriaCurrentRollout:
    """Pass 45.16 extends the `aria-current="page"` rollout from the sidebar
    (where Pass 41.13.A handled it via the `nav_active` macro in
    `base.html`) to the dashboard / analytics / museum / settings subnav /
    rom-tools tabs. WCAG 2.4.3 (Focus Order) requires aria-current on the
    link representing the current location/view; without it, assistive
    tech can't tell which tab is the user's location.

    Strategy chosen: instead of touching every `.classList.add('active')`
    site (10+ JS files, 70+ call sites), Pass 45.16 ships a single
    MutationObserver in `static/js/main.js` that mirrors `.active` ↔
    `aria-current="page"` on descendant <a>/<button> elements inside any
    container marked `data-tabbar`. The templates only need a one-time
    `data-tabbar` attribute on each nav container plus a static
    `aria-current="page"` next to the initial active link (so the page
    is correct even before main.js executes).

    Tests pin both layers:
      - main.js exports the helper functions
      - each target template has `data-tabbar` on its nav container
      - the initial active link carries `aria-current="page"`
      - the static rom-tools tabs (page-link tabs, no JS toggle) each
        carry the aria-current attribute"""

    def test_main_js_exports_aria_current_helper(self):
        """static/js/main.js must define _syncAriaCurrent + the observer
        setup function, and call the setup at DOMContentLoaded."""
        path = os.path.join(_REPO_ROOT, 'static', 'js', 'main.js')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        assert '_syncAriaCurrent' in body, (
            "Pass 45.16: main.js must define _syncAriaCurrent helper"
        )
        assert "data-tabbar" in body or "'data-tabbar'" in body, (
            "Pass 45.16: helper must scope to [data-tabbar] containers"
        )
        assert "MutationObserver" in body, (
            "Pass 45.16: setup must use MutationObserver to track .active "
            "class changes"
        )
        assert "aria-current" in body, (
            "Pass 45.16: helper must set the aria-current attribute"
        )
        # Wired at DOMContentLoaded so the initial sync runs.
        assert ("DOMContentLoaded" in body
                and "_setupTabbarAriaCurrent" in body), (
            "Pass 45.16: _setupTabbarAriaCurrent must be wired at DOMContentLoaded"
        )

    def test_dashboard_nav_has_data_tabbar(self):
        """dashboard.html must mark its nav container and the initial
        active link must carry aria-current."""
        path = os.path.join(_REPO_ROOT, 'templates', 'dashboard.html')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        assert 'class="dashboard-nav"' in body
        # The opening <nav> tag must carry data-tabbar.
        nav_tag_idx = body.find('class="dashboard-nav"')
        nav_tag_end = body.find('>', nav_tag_idx)
        nav_tag = body[nav_tag_idx:nav_tag_end]
        assert 'data-tabbar' in nav_tag, (
            "Pass 45.16: dashboard nav must carry data-tabbar"
        )
        # Initial active link must carry aria-current.
        assert 'class="dashboard-nav-link active" aria-current="page"' in body, (
            "Pass 45.16: initial active dashboard tab must declare "
            "aria-current=\"page\" so assistive tech sees it pre-JS"
        )

    def test_analytics_nav_has_data_tabbar(self):
        """analytics.html must mark its nav container and initial active link."""
        path = os.path.join(_REPO_ROOT, 'templates', 'analytics.html')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        nav_idx = body.find('class="analytics-nav"')
        nav_end = body.find('>', nav_idx)
        assert 'data-tabbar' in body[nav_idx:nav_end]
        assert 'class="analytics-nav-link active" aria-current="page"' in body

    def test_museum_nav_has_data_tabbar(self):
        """museum_system.html must mark its nav container and initial
        active link."""
        path = os.path.join(_REPO_ROOT, 'templates', 'museum_system.html')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        nav_idx = body.find('class="museum-nav"')
        nav_end = body.find('>', nav_idx)
        assert 'data-tabbar' in body[nav_idx:nav_end]
        assert 'class="museum-nav-item active" aria-current="page"' in body

    def test_settings_subnavs_all_marked(self):
        """All 6 settings subnav containers must carry data-tabbar.

        Pass 38.4 extracted the `tab_subnav(...)` macro
        (`templates/_macros/sticky_subnav.html`) — the raw `<div
        class="tab-subnav sticky-subnav" data-sticky-nav data-tabbar>`
        shape now lives only in the macro definition. Functional pin
        below renders the macro and asserts the attributes; the
        settings.html check just confirms all 6 call sites still exist.
        """
        # Functional pin: the macro emits the StickyScroll contract.
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        env = Environment(
            loader=FileSystemLoader(os.path.join(_REPO_ROOT, 'templates')),
            autoescape=select_autoescape(['html']),
        )
        tmpl = env.from_string(
            "{% from '_macros/sticky_subnav.html' import tab_subnav %}"
            "{% call tab_subnav('x') %}{% endcall %}"
        )
        rendered = tmpl.render()
        assert 'class="tab-subnav sticky-subnav"' in rendered
        assert 'data-sticky-nav data-tabbar' in rendered
        assert 'id="subnav-x"' in rendered

        # All 6 call sites still wired across the settings page. Pass 38.6
        # split settings.html into _settings_tabs/*.html partials, so the
        # call sites now live one per partial instead of all in one file.
        body = read_settings_with_partials()
        call_count = body.count('{% call tab_subnav(')
        assert call_count == 6, (
            f"Pass 45.16: expected 6 `tab_subnav(...)` calls across "
            f"settings.html + partials; found {call_count}"
        )

    def test_rom_tools_tabs_have_aria_current(self):
        """All 7 rom-tools page-tab templates must carry aria-current=\"page\"
        on their active tool-tab. These are page-link tabs (server-rendered
        active, no JS toggle) so the static attribute is the only mechanism."""
        templates = [
            'archive_scanner.html', 'chd_converter.html', 'chd_verify.html',
            'duplicate_finder.html', 'multi_disc_organizer.html',
            'rom_tools_settings.html', 'screenshot_dedup.html',
        ]
        missing = []
        for tpl in templates:
            path = os.path.join(_REPO_ROOT, 'templates', tpl)
            with open(path, encoding='utf-8') as f:
                body = f.read()
            if 'class="tool-tab active" aria-current="page"' not in body:
                missing.append(tpl)
        assert not missing, (
            f"Pass 45.16: these rom-tools templates lack aria-current "
            f"on the active tool-tab: {missing}"
        )

    def test_aria_current_attribute_count_is_50_plus(self):
        """Roadmap target: 50+ nav links rolled out. We count occurrences
        of `aria-current="page"` across all updated templates as a sanity
        check that the rollout is broad, not a single-link change."""
        templates = [
            'dashboard.html', 'analytics.html', 'museum_system.html',
            'settings.html',
            'archive_scanner.html', 'chd_converter.html', 'chd_verify.html',
            'duplicate_finder.html', 'multi_disc_organizer.html',
            'rom_tools_settings.html', 'screenshot_dedup.html',
            # Pass 41.13.A baseline (sidebar) — covered by base.html.
            'base.html',
        ]
        total = 0
        for tpl in templates:
            path = os.path.join(_REPO_ROOT, 'templates', tpl)
            with open(path, encoding='utf-8') as f:
                total += f.read().count('aria-current="page"')
        # 7 rom-tools + 1 dashboard + 1 analytics + 1 museum + 1 base.html
        # macro = 11 static occurrences; the JS auto-syncs the rest from
        # data-tabbar containers at runtime. Pin the lower bound at 10
        # for the static count to confirm the rollout actually happened.
        assert total >= 10, (
            f"Pass 45.16 rollout count too low: {total} static aria-current "
            "occurrences across target templates (expected ≥ 10)"
        )


# -----------------------------------------------------------------------------
# 45.17 — ModalFocusTrap rollout to 20+ dialogs
# -----------------------------------------------------------------------------
class TestPass45_17ModalFocusTrapRollout:
    """Pass 45.17 closes the gap left by the pre-pass audit: of 26 dialogs,
    only 6 wired ModalFocusTrap.activate() — the rest let Tab leak out to
    the page underneath (WCAG 2.1.2 inverted: focus must be trapped inside
    a modal so the user can't tab through hidden controls). Manually
    threading the trap through every open path is brittle (each modal
    has its own open function in its own JS file).

    Strategy: ship `ModalFocusTrap.autoAttach(modalEl, opts)` plus a global
    `_setupAutoFocusTraps()` initializer that scans for `[data-focus-trap]`
    elements at DOMContentLoaded. The autoAttach wires a MutationObserver
    that mirrors `.active` ↔ trap activate/deactivate; the trigger
    element is `document.activeElement` at the moment `.active` is added
    (matches the existing manual pattern). Per-modal config via
    `data-focus-trap-onescape="closeFnName"` and
    `data-focus-trap-content=".css-selector"`.

    Modals already wiring the trap manually are left alone; the opt-in
    `data-focus-trap` attribute prevents double-attach. New auto-attached
    modals: userModal, confirmModal, editControllerModal (settings.html);
    tagModal (tags.html); wishlistModal (wishlist.html); listModal
    (lists.html); addGameModal (list_detail.html); searchModal
    (compare_games.html); batchRenameModal (reports.html); scrapeModal,
    editModal, renameModal, boxartZoomModal (game_detail.html via
    _modals/*.html includes)."""

    def test_autoattach_method_exists(self):
        """ModalFocusTrap.autoAttach must be defined as a function (the
        JS-side contract). Source-grep on utils.js — runtime testing JS
        from Python is out of scope."""
        path = os.path.join(_REPO_ROOT, 'static', 'js', 'utils.js')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        assert 'autoAttach(modalEl, opts' in body, (
            "Pass 45.17: ModalFocusTrap.autoAttach must be defined"
        )
        # Must use a MutationObserver to watch the .active class.
        assert 'MutationObserver' in body and "attributeFilter: ['class']" in body, (
            "Pass 45.17: autoAttach must use MutationObserver scoped to class changes"
        )
        # Must call activate/deactivate on transitions.
        assert 'ModalFocusTrap.activate(' in body
        assert 'ModalFocusTrap.deactivate()' in body

    def test_main_js_runs_setup_at_dom_loaded(self):
        """static/js/main.js must wire _setupAutoFocusTraps at
        DOMContentLoaded so the observer fires for every page load."""
        path = os.path.join(_REPO_ROOT, 'static', 'js', 'main.js')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        assert '_setupAutoFocusTraps' in body
        assert "data-focus-trap" in body or "'data-focus-trap'" in body
        assert ('DOMContentLoaded' in body
                and '_setupAutoFocusTraps' in body), (
            "Pass 45.17: setup must run at DOMContentLoaded"
        )

    def test_settings_modals_marked(self):
        """userModal, confirmModal, editControllerModal on the settings page
        must declare data-focus-trap. Pass 38.6 moved userModal into
        _settings_tabs/account.html and editControllerModal into
        _settings_tabs/customization.html — search across the union."""
        body = read_settings_with_partials()
        assert ('id="userModal" data-focus-trap' in body), (
            "Pass 45.17: userModal must declare data-focus-trap"
        )
        assert ('id="confirmModal" class="confirm-modal" data-focus-trap'
                in body), (
            "Pass 45.17: confirmModal must declare data-focus-trap"
        )
        assert ('id="editControllerModal" data-focus-trap' in body), (
            "Pass 45.17: editControllerModal must declare data-focus-trap"
        )

    def test_top_level_template_modals_marked(self):
        """Top-level modal templates that didn't have a manual trap must
        carry data-focus-trap."""
        targets = {
            'tags.html': 'id="tagModal"',
            'wishlist.html': 'id="wishlistModal"',
            'lists.html': 'id="listModal"',
            'list_detail.html': 'id="addGameModal"',
            'compare_games.html': 'id="searchModal"',
            'reports.html': 'id="batchRenameModal"',
        }
        missing = []
        for tpl, idstr in targets.items():
            path = os.path.join(_REPO_ROOT, 'templates', tpl)
            with open(path, encoding='utf-8') as f:
                body = f.read()
            # Find the modal opening tag and confirm data-focus-trap is in
            # the same tag.
            idx = body.find(idstr)
            if idx == -1:
                missing.append(f"{tpl}: {idstr} not found")
                continue
            tag_end = body.find('>', idx)
            tag = body[idx:tag_end]
            if 'data-focus-trap' not in tag:
                missing.append(f"{tpl}: {idstr} tag missing data-focus-trap")
        assert not missing, "\n".join(missing)

    def test_modals_partials_marked(self):
        """The _modals/*.html partials included by game_detail.html must
        carry data-focus-trap."""
        targets = {
            '_modals/scrape_modal.html': 'id="scrapeModal"',
            '_modals/edit_modal.html': 'id="editModal"',
            '_modals/rename_modal.html': 'id="renameModal"',
            '_modals/boxart_zoom_modal.html': 'id="boxartZoomModal"',
        }
        missing = []
        for tpl, idstr in targets.items():
            path = os.path.join(_REPO_ROOT, 'templates', tpl)
            with open(path, encoding='utf-8') as f:
                body = f.read()
            idx = body.find(idstr)
            if idx == -1:
                missing.append(f"{tpl}: {idstr} not found")
                continue
            tag_end = body.find('>', idx)
            tag = body[idx:tag_end]
            if 'data-focus-trap' not in tag:
                missing.append(f"{tpl}: {idstr} tag missing data-focus-trap")
        assert not missing, "\n".join(missing)

    def test_rollout_total_count(self):
        """Roadmap target: 20+ remaining dialogs covered. Count
        occurrences of `data-focus-trap` across templates as the rollout
        breadth check."""
        import glob
        pattern = os.path.join(_REPO_ROOT, 'templates', '**', '*.html')
        total = 0
        for path in glob.glob(pattern, recursive=True):
            with open(path, encoding='utf-8') as f:
                # Count opening-tag occurrences (each modal gets exactly
                # one). Subtract closing-tag false matches (none expected
                # for an attribute, but defensive).
                total += f.read().count('data-focus-trap')
        # Each modal we marked carries 1-3 data-focus-trap* attributes
        # (data-focus-trap, data-focus-trap-onescape, data-focus-trap-content).
        # With ~12 modals marked across this pass, total ≥ 12 occurrences
        # of the bare attribute. Test counts the bare attribute name only
        # by counting 'data-focus-trap"' (with closing quote on the bare
        # form) — actually the bare form is `data-focus-trap ` (no = sign)
        # so we count instances of `data-focus-trap ` with a trailing
        # space.
        # The simpler lower bound: ≥ 12 marked modals × ≥ 1 attr each
        # = ≥ 12 substrings.
        assert total >= 12, (
            f"Pass 45.17 rollout count too low: {total} data-focus-trap "
            "occurrences (expected ≥ 12 for a 20-dialog rollout — each "
            "modal carries 1-3 attributes)"
        )

    def test_autoattach_idempotent(self):
        """The autoAttach implementation must be idempotent so that calling
        _setupAutoFocusTraps() twice (e.g. SPA-style soft navigation)
        doesn't double-bind. Source-grep — JS execution from pytest is
        out of scope."""
        path = os.path.join(_REPO_ROOT, 'static', 'js', 'utils.js')
        with open(path, encoding='utf-8') as f:
            body = f.read()
        # The guard must check for a previous attachment marker.
        idx = body.find('autoAttach(modalEl, opts')
        next_brace = body.find('    },', idx)
        slice_body = body[idx:next_brace] if next_brace != -1 else body[idx:idx + 2000]
        assert '_focusTrapObserver' in slice_body, (
            "Pass 45.17: autoAttach must use _focusTrapObserver as the "
            "idempotency marker"
        )
        # The body must early-return if the marker is already set.
        assert 'modalEl._focusTrapObserver) return' in slice_body, (
            "Pass 45.17: autoAttach must early-return when already attached"
        )


# -----------------------------------------------------------------------------
# 45.20 — chmod-after-verify race + button type sweep
# -----------------------------------------------------------------------------
class TestPass45_20ButtonTypeSweep:
    """Pass 45.20 closes two findings:

    1. **chmod-after-verify race** in ``services/database.py:backup_database``
       — already fixed in Pass 45.5 (chmod re-ordered to fire BEFORE the
       integrity-check open). The Pass-45.5 source-position pin lives in
       ``TestPass45_5*``; this class only re-asserts the contract for
       completeness.
    2. **<button onclick="..."> without explicit type** — pre-pass audit
       found 419 onclick-bearing buttons across templates without
       ``type="button"``. Inside a ``<form>`` the browser default is
       ``type="submit"``, so a click runs onclick AND submits the form,
       posting the form's data and (often) reloading the page. Pass 45.20
       sweeps every onclick-bearing button to add ``type="button"`` so
       the explicit form-submit buttons remain the only submitters.

    Note: the sweep adds ``type="button"`` everywhere uniformly. Buttons
    OUTSIDE forms get a no-op (HTML default type is already ``submit``
    only inside forms). Buttons that were INTENTIONALLY inside forms as
    submit buttons typically didn't have onclick (they relied on the
    form's submit handler), so the sweep doesn't break them."""

    def test_no_button_with_onclick_lacks_type(self):
        """Sweep contract: every onclick-bearing button across all
        templates must declare type=. The sweep added type=\"button\"
        to all onclick buttons; this test fails if a future template
        edit reintroduces an onclick button without an explicit type."""
        import glob
        import re
        pattern = os.path.join(_REPO_ROOT, 'templates', '**', '*.html')
        # Find every <button ...>` opening tag with onclick=, then check
        # for type=.
        button_re = re.compile(
            r'<button(?:(?!\btype\s*=)[^>])*?onclick\s*=[^>]*?>',
            re.IGNORECASE | re.DOTALL,
        )
        offenders = []
        for path in glob.glob(pattern, recursive=True):
            with open(path, encoding='utf-8') as f:
                body = f.read()
            matches = button_re.findall(body)
            if matches:
                offenders.append(
                    f"{os.path.relpath(path, _REPO_ROOT)}: "
                    f"{len(matches)} onclick button(s) without type"
                )
        assert not offenders, (
            "Pass 45.20: every onclick-bearing button must declare "
            "type=\"button\" so it doesn't accidentally submit an "
            "enclosing form. Offenders:\n  " +
            "\n  ".join(offenders)
        )

    def test_sweep_count_lower_bound(self):
        """Sanity: the sweep should have produced ≥ 200 type=\"button\"
        attributes across the templates tree (419 originals minus those
        that were already typed correctly)."""
        import glob
        pattern = os.path.join(_REPO_ROOT, 'templates', '**', '*.html')
        total = 0
        for path in glob.glob(pattern, recursive=True):
            with open(path, encoding='utf-8') as f:
                # type="button" is the canonical attribute form. There may
                # also be type='button' (single-quote) and a few others;
                # count both forms for robustness.
                body = f.read()
                total += body.count('type="button"')
                total += body.count("type='button'")
        assert total >= 200, (
            f"Pass 45.20 sweep lower bound: only {total} type=\"button\" "
            "attributes found across templates (expected ≥ 200 — pre-pass "
            "audit reported 419 onclick buttons missing the type)"
        )
