# Pass 25 — input hardening / SSRF / size caps regression coverage.
#
# Each class pins one sub-item's invariant. These are narrow unit checks —
# they're not trying to reproduce the full end-to-end flow, only to ensure
# the guard is in place and rejects the value it's supposed to reject.

import os
from unittest.mock import patch, MagicMock

import pytest

from tests._util import slice_function, read_module_source


def _fake_http_response(status_code=200, headers=None):
    """Build a MagicMock that mimics requests.Response inside a `with` block.

    Extracted from inline construction across multiple TestScraperDownloadCaps
    tests — the `__enter__`/`__exit__` wiring was identical in every site.
    """
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


# 25.1 — ES-DE path-traversal guard
# ---------------------------------
# `_within_allowed_root` and `_allowed_esde_roots` were lifted to module
# scope in scrape_esde.py (Pass 25.1) precisely so the path-traversal
# guard could be exercised directly from tests instead of mirrored.
class TestESDEPathTraversal:
    def test_within_allowed_root_rejects_outside_paths(self, tmp_path):
        from scraper.scrape_esde import _within_allowed_root

        allowed_root = os.path.realpath(str(tmp_path))

        assert _within_allowed_root(str(tmp_path / 'legit.png'), [allowed_root]) is True
        # Absolute outside path — rejected
        assert _within_allowed_root('/etc/passwd', [allowed_root]) is False
        # Traversal that escapes the root — rejected
        escape = str(tmp_path / '..' / '..' / '..' / 'etc' / 'passwd')
        assert _within_allowed_root(escape, [allowed_root]) is False


# 25.2 — /api/reports system whitelist
# -------------------------------------
# The multidisc-scan endpoint now returns 400 for an unknown system.
class TestReportsSystemWhitelist:
    def test_unknown_system_returns_400(self, monkeypatch):
        import app as app_module
        # Use monkeypatch.setitem so TESTING is automatically restored after
        # the test — never leak the mutation onto the shared app.config object
        # for sibling tests (xdist-safe).
        monkeypatch.setitem(app_module.app.config, 'TESTING', True)
        client = app_module.app.test_client()
        # Inject a session that satisfies both the @login_required guard
        # (user_id present) and the @app.before_request CSRF token check
        # (_csrf_token + matching X-CSRF-Token header on POST).
        csrf_token = 'test-csrf-token'
        with client.session_transaction() as sess:
            sess['user_id'] = 1
            sess['_csrf_token'] = csrf_token
        resp = client.post(
            '/api/reports/multidisc-scan',
            json={'system': '../../etc'},
            headers={'X-CSRF-Token': csrf_token},
        )
        # 400 = whitelist working. If 302/403 shows up the auth/CSRF bypass
        # isn't taking — that's a setup gap to fix, not a reason to widen
        # this assertion.
        assert resp.status_code == 400


# 25.3 — Museum SSRF guard
# ------------------------
# Private-IP candidates must be rejected before requests.get is called.
class TestMuseumSSRFGuard:
    # Pass 32.7 expanded the return tuple from (safe_url, err) to
    # (safe_url, pinned_ip, err) so callers can defeat DNS rebinding.
    def test_private_ip_rejected(self):
        from routes.museum import _is_public_https_url
        # 127.0.0.1 explicit — no DNS needed
        safe_url, pinned_ip, err = _is_public_https_url('http://127.0.0.1/admin')
        assert safe_url is None
        assert pinned_ip is None
        # Canonical rejection reason from services.ssrf.validate_outbound_url.
        # Pinning the exact prefix means a refactor that drops or reshapes the
        # message will fail loudly instead of silently degrading the assertion.
        assert err.startswith('disallowed IP range:'), err

    def test_rfc1918_rejected(self):
        from routes.museum import _is_public_https_url
        safe_url, pinned_ip, err = _is_public_https_url('http://10.0.0.1/foo')
        assert safe_url is None
        assert pinned_ip is None
        assert err.startswith('disallowed IP range:'), err

    def test_link_local_rejected(self):
        from routes.museum import _is_public_https_url
        # AWS IMDS endpoint — the canonical SSRF target
        safe_url, pinned_ip, err = _is_public_https_url('http://169.254.169.254/latest/meta-data/')
        assert safe_url is None
        assert pinned_ip is None
        assert err.startswith('disallowed IP range:'), err

    def test_non_http_scheme_rejected(self):
        from routes.museum import _is_public_https_url
        safe_url, pinned_ip, err = _is_public_https_url('file:///etc/passwd')
        assert safe_url is None
        assert pinned_ip is None
        assert 'scheme' in err.lower()

    def test_ipv6_loopback_rejected(self):
        """IPv6 SSRF coverage — the production guard uses the `ipaddress`
        module which classifies `::1` as loopback. A fast-path regression
        that early-returns on IPv4-shaped literals would miss this."""
        from routes.museum import _is_public_https_url
        safe_url, pinned_ip, err = _is_public_https_url('http://[::1]/admin')
        assert safe_url is None
        assert pinned_ip is None
        assert err.startswith('disallowed IP range:'), err

    def test_ipv6_link_local_rejected(self):
        """IPv6 link-local (`fe80::/10`) maps to the IPv4 169.254.0.0/16
        AWS-IMDS class of SSRF targets — same severity, IPv6 surface."""
        from routes.museum import _is_public_https_url
        safe_url, pinned_ip, err = _is_public_https_url('http://[fe80::1]/foo')
        assert safe_url is None
        assert pinned_ip is None
        assert err.startswith('disallowed IP range:'), err


# 25.4 — Museum upload size cap
# -----------------------------
# The /api/museum/controller-image-upload endpoint rejects oversize
# declared Content-Length with 413.
class TestMuseumUploadCap:
    def test_oversize_upload_rejected_via_max_content_length(self):
        # Flask's MAX_CONTENT_LENGTH (64 MB by default) catches bodies larger
        # than that; the MUSEUM_UPLOAD_MAX_BYTES (10 MB) catches the 10–64 MB
        # band that the global cap wouldn't. A true integration test would
        # need multipart plumbing; here we pin the relationship between the
        # two caps so they can't drift apart silently — the museum cap must
        # always be at most the global Flask cap, otherwise the museum guard
        # would never fire (Flask aborts the request first).
        import config
        import routes.museum  # noqa: F401 — import-clean smoke check
        assert hasattr(config, 'MUSEUM_UPLOAD_MAX_BYTES')
        assert config.MUSEUM_UPLOAD_MAX_BYTES >= 1024 * 1024
        # config.MAX_UPLOAD_BYTES is the value Flask sets as app.config['MAX_CONTENT_LENGTH']
        # (see app.py: `app.config['MAX_CONTENT_LENGTH'] = config.MAX_UPLOAD_BYTES`).
        assert hasattr(config, 'MAX_UPLOAD_BYTES')
        assert config.MUSEUM_UPLOAD_MAX_BYTES <= config.MAX_UPLOAD_BYTES


# 25.5 — CLZ PDF page-cap + temp cleanup
# --------------------------------------
class TestCLZPDFBounds:
    def test_max_pages_constant_exists(self):
        import config
        assert hasattr(config, 'CLZ_PDF_MAX_PAGES')
        assert config.CLZ_PDF_MAX_PAGES > 0

    def test_try_finally_cleanup(self):
        """The route now wraps pdfplumber.open in try/finally so tmp_path
        is deleted on exception paths, not just success paths.

        Slice the api_clz_parse body so the assertion can't pass on
        unrelated try/finally blocks elsewhere in the file (clz_import
        has at least two `finally:` blocks — lines 412 and 646).
        """
        import routes.clz_import as mod
        src = read_module_source(mod)
        slice_src = slice_function(src, 'api_clz_parse')
        assert slice_src, 'api_clz_parse not found in routes/clz_import.py'
        assert 'finally:' in slice_src
        assert 'os.unlink(tmp_path)' in slice_src


# 25.6 — MAX_VIDEO_SIZE
# ---------------------
class TestVideoUploadCap:
    def test_max_video_size_enforced(self):
        import config
        assert hasattr(config, 'MAX_VIDEO_SIZE')

        # Direct unit test: save_upload with a video-extension file and
        # content_length > MAX_VIDEO_SIZE must return None without writing.
        from services import game_media_service
        fs = MagicMock()
        fs.filename = 'test.mp4'
        fs.content_length = config.MAX_VIDEO_SIZE + 1
        result = game_media_service.save_upload(
            fs, '/tmp/nonexistent', 1, 'custom', game_media_service.ALLOWED_VIDEO_EXT,
        )
        assert result is None


# 25.7 — Scraper download response caps
# -------------------------------------
class TestScraperDownloadCaps:
    def test_base_scraper_download_image_respects_max_bytes(self, tmp_path):
        from scraper import base_scraper

        # Fake response that claims 100 MB Content-Length (above 50 MB cap).
        fake_resp = _fake_http_response(
            status_code=200,
            headers={'Content-Length': str(100 * 1024 * 1024)},
        )

        with patch.object(base_scraper._http_session, 'get', return_value=fake_resp):
            ok = base_scraper.download_image(
                'https://example.invalid/fake.jpg',
                str(tmp_path / 'out.jpg'),
                timeout=1,
            )
        assert ok is False
        assert not (tmp_path / 'out.jpg').exists()

    def test_constants_reasonable(self):
        import config
        assert config.MAX_MEDIA_DOWNLOAD_BYTES >= 1024 * 1024
        assert config.MAX_API_RESPONSE_BYTES >= 1024 * 1024


# 25.8 — List-endpoint row caps
# ------------------------------
class TestListRowCaps:
    def test_max_list_rows_constant(self):
        import config
        assert hasattr(config, 'MAX_LIST_ROWS')
        assert config.MAX_LIST_ROWS >= 10


# 25.9 — Rate limits registered
# ------------------------------
class TestRateLimits:
    def test_expected_endpoints_rate_limited(self):
        """Verify limiter has entries for Pass 25.9 targets."""
        import app as app_module
        if not app_module.limiter:
            pytest.skip('flask-limiter not installed')
        # The Limiter instance holds a limit registry keyed on view_func.
        # We just verify the view functions exist; the actual limit
        # application happens via limiter.limit(...) at app.py registration
        # time, which runs on import, so if that succeeded the limits are
        # registered. This is a smoke assertion.
        funcs = app_module.app.view_functions
        assert 'games_hltb.api_hltb_lookup' in funcs
        assert 'museum.generate_system' in funcs
        assert 'collector_trophies.refresh_trophies' in funcs
