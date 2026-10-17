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

import pytest


# 25.3 — Museum SSRF guard
# ------------------------
# Private-IP candidates must be rejected before requests.get is called.
class TestMuseumSSRFGuard:
    # Pass 32.7 expanded the return tuple from (safe_url, err) to
    # (safe_url, pinned_ip, err) so callers can defeat DNS rebinding.

    # Five IP-range cases share an identical assertion shape — collapsed
    # into one parametrize block (test-audit c-003 MED). The
    # `test_non_http_scheme_rejected` case stays standalone since it
    # asserts a different error prefix.
    @pytest.mark.parametrize("url,label", [
        ('http://127.0.0.1/admin', 'ipv4_loopback'),
        ('http://10.0.0.1/foo', 'rfc1918'),
        ('http://169.254.169.254/latest/meta-data/', 'ipv4_link_local_imds'),
        ('http://[::1]/admin', 'ipv6_loopback'),
        ('http://[fe80::1]/foo', 'ipv6_link_local'),
    ])
    def test_private_or_link_local_ip_rejected(self, url, label):
        """Every private/link-local IP class must produce the canonical
        `disallowed IP range:` rejection from
        `services.ssrf.validate_outbound_url`. Pinning the exact prefix
        means a refactor that drops or reshapes the message will fail
        loudly instead of silently degrading the assertion."""
        from routes.museum import _is_public_https_url
        safe_url, pinned_ip, err = _is_public_https_url(url)
        assert safe_url is None
        assert pinned_ip is None
        assert err.startswith('disallowed IP range:'), \
            f"[{label}] expected 'disallowed IP range:' prefix, got: {err!r}"

    def test_non_http_scheme_rejected(self):
        from routes.museum import _is_public_https_url
        safe_url, pinned_ip, err = _is_public_https_url('file:///etc/passwd')
        assert safe_url is None
        assert pinned_ip is None
        assert 'scheme' in err.lower()


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
