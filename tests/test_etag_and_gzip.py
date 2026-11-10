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

    def test_uncompressed_when_client_refuses_gzip_by_quality(self, client):
        # 'gzip;q=0' means "never gzip"; a substring check read it as yes (PASS-59-249).
        resp = client.get('/api/timezones', headers={'Accept-Encoding': 'gzip;q=0, identity'})
        assert resp.headers.get('Content-Encoding') != 'gzip'

    def test_small_responses_not_compressed(self, client):
        """Threshold guard: the CPU cost of gzipping sub-1KB bodies is
        usually a net loss over just sending them raw."""
        resp = client.get('/health', headers={'Accept-Encoding': 'gzip'})
        assert resp.status_code == 200
        assert resp.headers.get('Content-Encoding') is None


class TestCardDataETag:
    """If-None-Match against /api/games/card-data must short-circuit with 304."""

    def test_request_parity(self, admin_test_client):
        """Two requests with identical If-None-Match must hit the 304 fast
        path after the first populates the ETag.

        The ETag is a hash of the reply, so an id with no row still gets one;
        no game rows are needed. It used to skip on every run: without the
        admin stub the first-run setup gate answered 503 (PASS-59-290)."""
        client, _csrf = admin_test_client()

        resp1 = client.get('/api/games/card-data?ids=1')
        assert resp1.status_code == 200, resp1.get_data(as_text=True)[:200]
        etag = resp1.headers.get('ETag')
        assert etag and etag.startswith('W/"'), f"expected weak ETag, got {etag!r}"

        resp2 = client.get('/api/games/card-data?ids=1',
                           headers={'If-None-Match': etag})
        assert resp2.status_code == 304
        assert resp2.headers.get('ETag') == etag
        # 304 must have no body per RFC 7232.
        assert not resp2.data
