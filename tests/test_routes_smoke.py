# Integration smoke tests — verify route blueprints register correctly
# and that authentication decorators actually guard protected endpoints.
#
# These live in the same Flask app instance the production server uses,
# so any import-time crash in a blueprint (missing dependency, broken
# decorator chain) fails here before it fails in prod.

import pytest


# Note: the `app_client` fixture lives in tests/conftest.py — function-scoped
# (not module-scoped) so monkeypatch is available. Tests that previously took
# `client` now take `app_client`.


class TestRouteRegistration:
    """All extracted blueprints must be registered and reachable.

    Regression test: after v2.77.9 / v2.77.10 split, these endpoints live
    in separate blueprint modules and are easy to forget to re-register.
    """

    EXPECTED_ENDPOINTS = {
        # Core games blueprint
        'games.all_games': '/games',
        'games.api_games': '/api/games',
        'games.game_detail': '/game/<int:game_id>',
        # HLTB blueprint (v2.77.9)
        'games_hltb.api_hltb_lookup': '/api/hltb-lookup/<int:game_id>',
        'games_hltb.api_hltb_search': '/api/hltb/search',
        # HLTB bulk + review queue (v2.83.0)
        'games_hltb.hltb_review_page': '/hltb/review',
        'games_hltb.api_hltb_bulk_start': '/api/hltb/bulk/start',
        'games_hltb.api_hltb_bulk_status': '/api/hltb/bulk/status',
        'games_hltb.api_hltb_bulk_cancel': '/api/hltb/bulk/cancel',
        'games_hltb.api_hltb_pending_list': '/api/hltb/pending',
        'games_hltb.api_hltb_pending_approve': '/api/hltb/pending/<int:pending_id>/approve',
        'games_hltb.api_hltb_pending_reject': '/api/hltb/pending/<int:pending_id>/reject',
        'games_hltb.api_hltb_pending_approve_all': '/api/hltb/pending/approve-all',
        'games_hltb.api_hltb_pending_reject_all': '/api/hltb/pending/reject-all',
        # Alt-titles backfill (v2.83.0)
        'maintenance.api_alt_titles_backfill_start': '/api/maintenance/alt-titles-backfill/start',
        'maintenance.api_alt_titles_backfill_status': '/api/maintenance/alt-titles-backfill/status',
        'maintenance.api_alt_titles_backfill_cancel': '/api/maintenance/alt-titles-backfill/cancel',
        # Missing-media-ref sweep (Pass 54.1) — admin-guarded, and absent from
        # this map meant they escaped the auth sweep below too (Pass 57.7 item 6).
        'maintenance.api_missing_media_refs_preview': '/api/missing-media-refs/preview',
        'maintenance.api_missing_media_refs_clear': '/api/missing-media-refs/clear',
        # AI blueprint (v2.77.10)
        'games_ai.api_game_ai_fill': '/api/game/<int:game_id>/ai-fill',
        # Search/compare blueprint (v2.77.10)
        'games_search.api_search_games': '/api/games/search',
        'games_search.api_local_search_games': '/api/games/find',
        'games_search.api_similar_games': '/api/games/<int:game_id>/similar',
        'games_search.compare_games_page': '/compare',
        'games_search.api_compare_games': '/api/games/compare',
        # Media blueprint (v2.77.10)
        'games_media.api_delete_game': '/api/delete-game/<int:game_id>',
        'games_media.api_rename_rom': '/api/rename-rom/<int:game_id>',
        'games_media.api_delete_screenshot': '/api/delete-screenshot/<int:game_id>',
    }

    def test_all_expected_endpoints_exist(self, app_client):
        import app as app_module
        rules = {r.endpoint: r.rule for r in app_module.app.url_map.iter_rules()}
        missing = []
        for endpoint, expected_rule in self.EXPECTED_ENDPOINTS.items():
            if endpoint not in rules:
                missing.append(f"{endpoint} (expected rule: {expected_rule})")
            elif rules[endpoint] != expected_rule:
                missing.append(f"{endpoint} rule changed: {rules[endpoint]!r} != {expected_rule!r}")
        assert not missing, "Missing/changed endpoints:\n  " + "\n  ".join(missing)


class TestAuthGuards:
    """Protected endpoints must redirect unauthenticated users to /login."""

    # Expanded auth-guard sweep (test-audit c-006 MED): the previous
    # 5-route list covered only a sample of the 22 EXPECTED_ENDPOINTS.
    # Below we drive every protected GET endpoint that doesn't require
    # a path-variable lookup (the `<int:game_id>` routes get covered by
    # the explicit `/api/delete-game/1` etc. cases). A blueprint that
    # registers cleanly but 500s on every authenticated request used to
    # slip through this smoke layer.
    @pytest.mark.parametrize("path", [
        '/games',
        '/compare',
        '/api/games',
        '/api/games/find?q=test',
        '/api/games/search?title=test',
        '/hltb/review',
        '/api/hltb/bulk/status',
        '/api/hltb/pending',
        '/api/maintenance/alt-titles-backfill/status',
        '/api/games/compare?ids=1,2',
        '/api/games/1/similar',
        # admin_required, not login_required — same unauthenticated redirect.
        '/api/missing-media-refs/preview',
        # Pass 41.9 — `/api/recently-viewed` removed (zero callers; the
        # dashboard reads `user_game_views` directly via app.py).
    ])
    def test_protected_get_denies_unauthenticated(self, app_client, path):
        """An unauthenticated GET is refused -- in the shape its caller reads.

        The contract being asserted is unchanged: none of these serves
        content to an anonymous caller. What changed on 2026-09-01 is the
        SHAPE of the refusal, and this test previously pinned the wrong one.

        api-contracts.md invariant 1: "Every /api/* route returns JSON,
        never HTML or a redirect" -- and a redirect here is worse than
        untidy, because fetch() follows it and the calling JS sees a 200
        carrying dashboard HTML. So /api/* must answer 401 with the
        envelope; a page route still redirects to /login or /setup.

        This is a stronger assertion than the one it replaces: it proves the
        envelope as well as the refusal.
        """
        resp = app_client.get(path, follow_redirects=False)

        if path.startswith('/api/'):
            assert resp.status_code == 401, (
                f"{path} must answer an anonymous caller with 401 JSON, "
                f"got {resp.status_code}. A 3xx here is the Pass 45.1 defect: "
                f"fetch() follows it and the caller reads 200-with-HTML as "
                f"success."
            )
            body = resp.get_json()
            assert body is not None, f"{path} returned non-JSON to an anonymous caller"
            assert body.get('success') is False, f"{path}: {body!r}"
        else:
            # Page routes keep the redirect. Destination is /login on a
            # set-up install, or /setup when the first-time-setup middleware
            # detects a blank DB (e.g. on a fresh CI runner).
            assert resp.status_code in (301, 302, 303), \
                f"Expected redirect for {path}, got {resp.status_code}"
            location = resp.headers.get('Location', '')
            assert '/login' in location or '/setup' in location, \
                f"Expected redirect to /login or /setup for {path}, got {location!r}"

    @pytest.mark.parametrize("path", [
        '/api/delete-game/1',
        '/api/rename-rom/1',
        '/api/delete-screenshot/1',
        '/api/hltb/bulk/start',
        '/api/hltb/bulk/cancel',
        '/api/hltb/pending/1/approve',
        '/api/hltb/pending/1/reject',
        '/api/hltb/pending/approve-all',
        '/api/hltb/pending/reject-all',
        '/api/game/1/ai-fill',
        '/api/maintenance/alt-titles-backfill/start',
        '/api/maintenance/alt-titles-backfill/cancel',
        # Clears DB media references library-wide — the most destructive
        # unauthenticated POST in this file (Pass 57.7 item 6).
        '/api/missing-media-refs/clear',
    ])
    def test_protected_post_redirects_unauthenticated(self, app_client, path):
        """Write endpoints must reject unauthenticated POSTs. An unauthenticated
        POST to a mutating endpoint is more dangerous than a GET — pin the
        login_required guard on a sample of them."""
        resp = app_client.post(path, follow_redirects=False)
        # Same shape as the GET case: 30x redirect to /login or /setup, or a
        # 4xx explicit rejection (401/403). Either proves the endpoint isn't
        # mutating state for unauthenticated callers.
        assert resp.status_code in (301, 302, 303, 401, 403), \
            f"Expected auth rejection for POST {path}, got {resp.status_code}"
        if resp.status_code in (301, 302, 303):
            location = resp.headers.get('Location', '')
            assert '/login' in location or '/setup' in location, \
                f"Expected redirect to /login or /setup for POST {path}, got {location!r}"

    def test_login_page_accessible(self, app_client):
        resp = app_client.get('/login', follow_redirects=False)
        # /login itself must be reachable without auth. On a fresh install the
        # first-time-setup middleware may redirect it to /setup; either is OK.
        if resp.status_code in (301, 302, 303):
            assert '/setup' in resp.headers.get('Location', '')
        else:
            assert resp.status_code == 200


class TestHLTBSearchAuth:
    """HLTB endpoints should reject unauthenticated POSTs."""

    def test_hltb_search_requires_auth(self, app_client):
        resp = app_client.post('/api/hltb/search', json={'query': 'test'},
                               follow_redirects=False)
        assert resp.status_code in (301, 302, 303, 401, 403), \
            f"HLTB search should require auth, got {resp.status_code}"


class TestLocalSearchInputValidation:
    """Tests for /api/games/find input-handling that don't require DB state."""

    def test_find_requires_login(self, app_client):
        # 2026-09-01: was a 302 assertion. /api/* now answers 401 JSON per
        # api-contracts.md invariant 1 -- the refusal is unchanged, its
        # shape is not. See TestAuthGuards for the full reasoning.
        resp = app_client.get('/api/games/find?q=zelda', follow_redirects=False)
        assert resp.status_code == 401, \
            f"/api/games/find should require auth (401 JSON), got {resp.status_code}"
        body = resp.get_json()
        assert body is not None and body.get('success') is False, f"{body!r}"
