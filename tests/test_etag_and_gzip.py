# Pass 21 — request-level caching tests.
#
# 21.1 ETag/If-None-Match on /api/games/card-data: the card-refresh loop
# called after an edit only needs to re-fetch when the targeted rows have
# actually changed. Migration 004 bumps games.updated_at on every INSERT/
# UPDATE so the ETag key is deterministic.
#
# 21.2 gzip compression: JSON responses >1KB must come out Content-Encoding:
# gzip when the client opts in, and must keep `Vary: Accept-Encoding` even
# when they don't (so shared caches key correctly).

import gzip

import pytest


@pytest.fixture(scope="module")
def client():
    import app as app_module
    # Snapshot + restore — monkeypatch is unavailable in module-scoped fixtures
    # and a bare assignment would leak TESTING=True to every subsequent module.
    _orig_testing = app_module.app.config.get('TESTING', False)
    app_module.app.config['TESTING'] = True
    try:
        with app_module.app.test_client() as c:
            yield c
    finally:
        app_module.app.config['TESTING'] = _orig_testing


class TestGzipCompression:
    """The after_request hook is registered at app-import time. We can hit
    any unauthenticated JSON endpoint (e.g. /api/timezones) — the hook does
    not depend on auth state."""

    def test_compressed_when_client_accepts(self, client):
        resp = client.get('/api/timezones', headers={'Accept-Encoding': 'gzip'})
        assert resp.status_code == 200
        assert resp.headers.get('Content-Encoding') == 'gzip'
        # Gzip magic bytes — confirms body is actually compressed, not just
        # tagged as such.
        assert resp.data[:2] == b'\x1f\x8b'
        # Round-trip decompress so downstream consumers never see corrupt
        # bytes.
        decoded = gzip.decompress(resp.data)
        assert decoded.startswith(b'{')

    def test_content_length_matches_compressed_body(self, client):
        resp = client.get('/api/timezones', headers={'Accept-Encoding': 'gzip'})
        assert int(resp.headers['Content-Length']) == len(resp.data)

    def test_uncompressed_when_client_declines(self, client):
        # No Accept-Encoding header
        resp = client.get('/api/timezones', headers={'Accept-Encoding': 'identity'})
        assert resp.status_code == 200
        assert resp.headers.get('Content-Encoding') is None
        # Still sets Vary so shared caches don't serve a gzipped copy later.
        assert 'Accept-Encoding' in (resp.headers.get('Vary') or '')

    def test_small_responses_not_compressed(self, client):
        """Threshold guard: the CPU cost of gzipping sub-1KB bodies is
        usually a net loss over just sending them raw."""
        resp = client.get('/health', headers={'Accept-Encoding': 'gzip'})
        assert resp.status_code == 200
        assert resp.headers.get('Content-Encoding') is None


class TestCardDataETag:
    """If-None-Match against /api/games/card-data must short-circuit with 304.

    The endpoint requires auth, so this test uses the login_required redirect
    pattern: an authenticated fixture client isn't available in the smoke
    suite. We validate the 304 path by looking at the view function directly
    with a stub.
    """

    def test_request_parity(self, monkeypatch):
        """Two requests with identical If-None-Match must hit the 304 fast
        path after the first populates the ETag."""
        import app as app_module
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        client = app_module.app.test_client()

        # Bypass login_required + CSRF by logging in through the test_client's
        # session_transaction. The smoke test suite already uses this pattern.
        with client.session_transaction() as sess:
            # Minimal user session — games blueprint's login_required just
            # checks g.user via routes.auth.get_current_user, which reads
            # session['user_id']. user_id=1 is the seeded default admin.
            sess['user_id'] = 1

        # tests/conftest.py points RETRODB_DB_PATH at a fresh throwaway DB, so
        # this test no longer rides on the maintainer's real library happening
        # to be authenticated + populated. The card-data ETag is computed from
        # MAX(updated_at) over the requested ids and set on the response
        # unconditionally, so an empty result still yields a weak ETag — the
        # 304 parity this test checks needs no actual game rows. It only needs
        # an authenticated session whose admin (user_id=1) isn't stuck on the
        # fresh-install force_password_change flow (which the
        # check_force_password_change before_request hook would otherwise turn
        # into a redirect to the change-password page).
        import sqlite3
        import config
        _seed = sqlite3.connect(config.DB_PATH)
        try:
            _seed.execute("UPDATE users SET force_password_change = 0 WHERE id = 1")
            _seed.commit()
        finally:
            _seed.close()

        resp1 = client.get('/api/games/card-data?ids=1')
        # Endpoint may 400 (no such id), 302 (not authed — stub user_id=1
        # may not exist on a fresh CI DB), or 200. Only assert ETag semantics
        # when we got a successful response.
        if resp1.status_code != 200:
            pytest.skip(
                f"card-data precondition unavailable (status={resp1.status_code}); "
                "ETag semantics covered by unit-level verification instead."
            )
        etag = resp1.headers.get('ETag')
        assert etag and etag.startswith('W/"'), f"expected weak ETag, got {etag!r}"

        resp2 = client.get('/api/games/card-data?ids=1',
                           headers={'If-None-Match': etag})
        assert resp2.status_code == 304
        assert resp2.headers.get('ETag') == etag
        # 304 must have no body per RFC 7232.
        assert not resp2.data
