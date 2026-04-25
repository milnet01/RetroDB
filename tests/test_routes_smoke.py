# Integration smoke tests — verify route blueprints register correctly
# and that authentication decorators actually guard protected endpoints.
#
# These live in the same Flask app instance the production server uses,
# so any import-time crash in a blueprint (missing dependency, broken
# decorator chain) fails here before it fails in prod.

import pytest


@pytest.fixture(scope="module")
def client():
    import app as app_module
    app_module.app.config['TESTING'] = True
    with app_module.app.test_client() as c:
        yield c


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

    def test_all_expected_endpoints_exist(self, client):
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

    @pytest.mark.parametrize("path", [
        '/games',
        '/compare',
        '/api/games',
        '/api/games/find?q=test',
        '/api/games/search?title=test',
        # Pass 41.9 — `/api/recently-viewed` removed (zero callers; the
        # dashboard reads `user_game_views` directly via app.py).
    ])
    def test_protected_get_redirects_unauthenticated(self, client, path):
        resp = client.get(path, follow_redirects=False)
        # login_required redirects unauthenticated GETs. Destination is /login
        # on a set-up install, or /setup when the first-time-setup middleware
        # detects a blank DB (e.g. on a fresh CI runner). Either proves the
        # endpoint is not serving content to unauthenticated callers.
        assert resp.status_code in (301, 302, 303), \
            f"Expected redirect for {path}, got {resp.status_code}"
        location = resp.headers.get('Location', '')
        assert '/login' in location or '/setup' in location, \
            f"Expected redirect to /login or /setup for {path}, got {location!r}"

    def test_login_page_accessible(self, client):
        resp = client.get('/login', follow_redirects=False)
        # /login itself must be reachable without auth. On a fresh install the
        # first-time-setup middleware may redirect it to /setup; either is OK.
        if resp.status_code in (301, 302, 303):
            assert '/setup' in resp.headers.get('Location', '')
        else:
            assert resp.status_code == 200


class TestHLTBSearchAuth:
    """HLTB endpoints should reject unauthenticated POSTs."""

    def test_hltb_search_requires_auth(self, client):
        resp = client.post('/api/hltb/search', json={'query': 'test'},
                           follow_redirects=False)
        assert resp.status_code in (301, 302, 303, 401, 403), \
            f"HLTB search should require auth, got {resp.status_code}"


class TestLocalSearchInputValidation:
    """Tests for /api/games/find input-handling that don't require DB state."""

    def test_find_requires_login(self, client):
        resp = client.get('/api/games/find?q=zelda', follow_redirects=False)
        assert resp.status_code in (301, 302, 303), \
            f"/api/games/find should require auth, got {resp.status_code}"
        location = resp.headers.get('Location', '')
        assert '/login' in location or '/setup' in location
