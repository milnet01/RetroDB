# HTTP security header smoke tests — pins the Pass 16 header contract so
# future refactors don't regress the modern header set (X-XSS-Protection
# removed, Permissions-Policy added, HSTS env-gated, CSP report-only).

import pytest


@pytest.fixture(scope="module")
def client():
    import app as app_module
    # Snapshot + restore — monkeypatch is not available in module-scoped fixtures,
    # and a bare assignment would leak TESTING=True to every subsequent module.
    _orig_testing = app_module.app.config.get('TESTING', False)
    app_module.app.config['TESTING'] = True
    try:
        with app_module.app.test_client() as c:
            yield c
    finally:
        app_module.app.config['TESTING'] = _orig_testing


class TestLegacyHeadersStillPresent:
    """The three baseline headers from Pass 11 must remain."""

    def test_content_type_options(self, client):
        resp = client.get('/health')
        assert resp.headers.get('X-Content-Type-Options') == 'nosniff'

    def test_frame_options(self, client):
        resp = client.get('/health')
        assert resp.headers.get('X-Frame-Options') == 'SAMEORIGIN'

    def test_referrer_policy(self, client):
        resp = client.get('/health')
        assert resp.headers.get('Referrer-Policy') == 'strict-origin-when-cross-origin'


class TestXxssProtectionRemoved:
    """16.1: The deprecated X-XSS-Protection header must not be sent."""

    def test_xxss_protection_absent(self, client):
        resp = client.get('/health')
        assert 'X-XSS-Protection' not in resp.headers


class TestPermissionsPolicy:
    """16.3: Opt out of browser APIs RetroDB never uses."""

    def test_permissions_policy_present(self, client):
        resp = client.get('/health')
        assert 'Permissions-Policy' in resp.headers

    @pytest.mark.parametrize("feature", [
        'camera', 'microphone', 'geolocation',
        'payment', 'usb', 'interest-cohort',
        'browsing-topics',
    ])
    def test_permissions_policy_disables_sensors(self, client, feature):
        # Parametrized so each feature is its own pytest node — a regression
        # that drops 3 of the 7 features shows all three failures at once
        # instead of stopping at the first.
        resp = client.get('/health')
        pp = resp.headers['Permissions-Policy']
        assert f'{feature}=()' in pp, f"{feature} not disabled in Permissions-Policy"


class TestHstsEnvGated:
    """16.4: HSTS only when SESSION_COOKIE_SECURE is on (TLS in front)."""

    def test_hsts_absent_on_plain_http(self, client, monkeypatch):
        # Default test config has SESSION_COOKIE_SECURE=False
        import app as app_module
        monkeypatch.setitem(app_module.app.config, 'SESSION_COOKIE_SECURE', False)
        resp = client.get('/health')
        assert 'Strict-Transport-Security' not in resp.headers

    def test_hsts_present_when_secure_cookies_enabled(self, client):
        import app as app_module
        original = app_module.app.config.get('SESSION_COOKIE_SECURE')
        try:
            app_module.app.config['SESSION_COOKIE_SECURE'] = True
            resp = client.get('/health')
            hsts = resp.headers.get('Strict-Transport-Security', '')
            assert 'max-age=' in hsts
            assert 'includeSubDomains' in hsts
        finally:
            app_module.app.config['SESSION_COOKIE_SECURE'] = original


class TestCspReportOnly:
    """16.2: CSP ships in Report-Only until template migration is done."""

    def test_csp_report_only_present(self, client):
        resp = client.get('/health')
        assert 'Content-Security-Policy-Report-Only' in resp.headers

    def test_csp_enforcing_not_sent(self, client):
        """While templates still use inline handlers, the enforcing header
        must stay absent — otherwise pages would break silently."""
        resp = client.get('/health')
        assert 'Content-Security-Policy' not in resp.headers

    def test_csp_has_nonce(self, client):
        resp = client.get('/health')
        csp = resp.headers['Content-Security-Policy-Report-Only']
        assert "'nonce-" in csp

    def test_csp_nonce_changes_per_request(self, client):
        import re
        resp1 = client.get('/health')
        resp2 = client.get('/health')
        pat = re.compile(r"'nonce-([^']+)'")
        csp1 = resp1.headers['Content-Security-Policy-Report-Only']
        csp2 = resp2.headers['Content-Security-Policy-Report-Only']
        m1 = pat.search(csp1)
        m2 = pat.search(csp2)
        assert m1 is not None, f"Nonce not found in CSP: {csp1[:100]}"
        assert m2 is not None, f"Nonce not found in CSP: {csp2[:100]}"
        assert m1.group(1) != m2.group(1), "CSP nonce must be per-request, not reused"

    @pytest.mark.parametrize("directive", [
        'default-src', 'script-src', 'style-src',
        'img-src', 'font-src', 'connect-src',
        'frame-ancestors', 'base-uri', 'form-action',
    ])
    def test_csp_includes_core_directives(self, client, directive):
        # Parametrized so multi-directive regressions show all failures at once.
        resp = client.get('/health')
        csp = resp.headers['Content-Security-Policy-Report-Only']
        assert directive in csp, f"Missing directive: {directive}"

    def test_csp_blocks_objects(self, client):
        resp = client.get('/health')
        csp = resp.headers['Content-Security-Policy-Report-Only']
        assert "object-src 'none'" in csp


class TestCspNonceInTemplateContext:
    """The {{ csp_nonce }} Jinja global must match what's sent in the header.

    A two-nonce split — context processor and response writer reading different
    attributes — would silently break every inline `<script nonce="…">` because
    the nonce in the rendered HTML wouldn't appear in the CSP header.
    """

    def test_nonce_in_template_matches_g_csp_nonce(self):
        """Match contract — the value the template renders must be the same
        value `services.middleware.set_security_headers` puts in the header
        (both read `flask.g.csp_nonce`). Equality, not just non-empty."""
        import app as app_module
        from flask import g, render_template_string
        with app_module.app.test_request_context('/', method='GET'):
            app_module.assign_request_id()
            rendered = render_template_string('{{ csp_nonce }}')
            assert rendered == g.csp_nonce, (
                f"Template renders {rendered!r}; g.csp_nonce={g.csp_nonce!r} — "
                "context processor and request hook disagree"
            )
            assert len(rendered) >= 20  # token_urlsafe(16) is ~22 chars

    def test_response_header_nonce_matches_template_nonce(self, client):
        """End-to-end pair: a real request's CSP header nonce must equal the
        Jinja-rendered nonce for the same request. Captures the value via a
        per-request before_request hook so we don't rely on /health rendering
        anything (it returns JSON)."""
        import re
        import app as app_module
        import flask
        captured = {}

        # Use a one-shot after_request hook to capture g.csp_nonce for this
        # request only. monkeypatch isn't needed — the hook is wrapped in a
        # try/finally that pops it off the app's deferred-callbacks list.
        def _capture():
            captured['nonce'] = flask.g.get('csp_nonce', '')
        app_module.app.before_request_funcs.setdefault(None, []).append(
            lambda: _capture()
        )
        try:
            resp = client.get('/health')
        finally:
            app_module.app.before_request_funcs[None].pop()

        csp = resp.headers.get('Content-Security-Policy-Report-Only', '')
        m = re.search(r"'nonce-([^']+)'", csp)
        assert m is not None, f"No nonce in CSP header: {csp[:200]}"
        header_nonce = m.group(1)
        assert captured['nonce'] == header_nonce, (
            f"Template-side nonce ({captured['nonce']!r}) does not match "
            f"the header nonce ({header_nonce!r}) — silent inline-script "
            "blocking risk"
        )
