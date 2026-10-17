# Pass 25 — input hardening / SSRF / size caps regression coverage.
#
# Each class pins one sub-item's invariant. These are narrow unit checks —
# they're not trying to reproduce the full end-to-end flow, only to ensure
# the guard is in place and rejects the value it's supposed to reject.
#
# Split by subsystem so the Flask app import only fires where a test needs it:
#   test_input_hardening_app.py      — 25.2 reports whitelist, 25.9 rate limits
#   test_input_hardening_scrapers.py — 25.1 ES-DE path traversal, 25.7 download caps
#   test_input_hardening_museum.py   — 25.3 SSRF guard, 25.4 upload cap
#   test_input_hardening_uploads.py  — 25.5 CLZ PDF bounds, 25.6 video cap, 25.8 row caps

import os
from unittest.mock import patch, MagicMock


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
