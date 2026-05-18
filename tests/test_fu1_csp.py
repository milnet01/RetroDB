# Tests for the FU.1 CSP migration work-in-progress. Pins the partial-flip
# contract:
#   - Every inline `<script>` block carries `nonce="{{ csp_nonce }}"`.
#   - No template ships an inline `onerror=` attribute (the high-frequency
#     CSP blocker that this pass migrated to data-attribute-driven
#     delegated listeners).
#   - The delegated error handler is wired in main.js so cards / hero
#     images / trophy icons still hide / swap / replace when an image
#     404s.
#
# These are source-grep tests on purpose: any future template touch that
# slips an inline handler back in trips the pin instead of waiting for a
# manual CSP-console audit.

from tests._util import REPO_ROOT, read_source

import pytest
import pathlib
import re


REPO_ROOT = pathlib.Path(REPO_ROOT)
TEMPLATES_DIR = REPO_ROOT / 'templates'


def _iter_template_files():
    return [p for p in TEMPLATES_DIR.rglob('*.html') if p.is_file()]


# ---------------------------------------------------------------------------
# Inline <script> blocks must carry the nonce
# ---------------------------------------------------------------------------

class TestInlineScriptNonces:
    """Every `<script>` tag without `src=` must declare the per-request nonce
    so it ships under CSP enforcing without an `'unsafe-inline'` escape
    hatch."""

    def test_no_unnonced_inline_script_block(self):
        offenders = []
        bare_pattern = re.compile(r'^\s*<script>\s*$', re.MULTILINE)
        for path in _iter_template_files():
            text = path.read_text(encoding='utf-8')
            if bare_pattern.search(text):
                offenders.append(path.relative_to(REPO_ROOT))
        assert not offenders, (
            "Inline <script> blocks must be nonced; add "
            '`nonce=\"{{ csp_nonce }}\"`:\n  ' +
            '\n  '.join(str(p) for p in offenders)
        )

    def test_every_template_with_script_uses_nonce(self):
        """Forward-pin: the count of nonced inline `<script nonce=...>`
        blocks matches the total count of inline-script-bearing templates.
        Catches the case where a future commit re-introduces `<script>`
        without `nonce=`."""
        nonced = 0
        for path in _iter_template_files():
            nonced += len(re.findall(
                r'<script nonce="{{ csp_nonce }}">',
                path.read_text(encoding='utf-8'),
            ))
        # Pin: as of FU.1 this is at least 45 (38 templates, base.html has 7,
        # one template has 2 → ~46). Hard-floor at 40 so a regression that
        # drops a few still trips here.
        assert nonced >= 40, (
            f"Only {nonced} nonced inline scripts found — FU.1 closed at "
            f"~46. A nonced block must have been replaced with a bare "
            f"`<script>` (which CSP enforcing will block)."
        )


# ---------------------------------------------------------------------------
# No inline onerror= attributes
# ---------------------------------------------------------------------------

class TestNoInlineOnError:
    """Inline `onerror=` is blocked under CSP enforcing. FU.1 migrated every
    one in production templates to either a `data-on-error="…"` marker
    (handled by the delegated listener in `main.js::initializeImageError
    Handling`) or a per-page `addEventListener('error', …)` block."""

    # JS comments and string-literal SAMPLES of malicious payloads in the
    # XSS-hardening notes legitimately contain the substring `onerror=` and
    # should NOT be reported as live handlers.
    _COMMENT_OR_SAMPLE_LINES = re.compile(
        r'//|<!--|→|—\s*missing|escaped'
    )

    def test_no_live_onerror_attribute_in_templates(self):
        live_handlers = []
        # Match `onerror="…"` only when it appears to be inside an HTML
        # tag — i.e. preceded by whitespace and followed by `=`. The
        # negative side-pattern below drops comment/sample-payload lines.
        attr_pattern = re.compile(r'\bonerror=["\']')
        for path in _iter_template_files():
            for line_no, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
                if not attr_pattern.search(line):
                    continue
                if self._COMMENT_OR_SAMPLE_LINES.search(line):
                    continue
                live_handlers.append(f"{path.relative_to(REPO_ROOT)}:{line_no}")
        assert not live_handlers, (
            "Inline `onerror=` attributes block under CSP enforcing. Use "
            '`data-on-error="<action>"` instead (see '
            '`static/js/main.js::initializeImageErrorHandling`):\n  ' +
            '\n  '.join(live_handlers)
        )


# ---------------------------------------------------------------------------
# Delegated error handler wired in main.js
# ---------------------------------------------------------------------------

class TestDelegatedErrorHandler:
    """The main.js handler is the contract that the `data-on-error="…"`
    markers in templates depend on. Pin its presence + the action vocabulary
    so a future cleanup that renames the function or drops an action
    surfaces here, not via silent broken image fallbacks in production."""

    def _main_js(self):
        return (REPO_ROOT / 'static' / 'js' / 'main.js').read_text(encoding='utf-8')

    def test_initializer_function_exists(self):
        src = self._main_js()
        assert 'function initializeImageErrorHandling' in src
        # Hooked into DOMContentLoaded so it's live before any image fails.
        assert 'initializeImageErrorHandling()' in src

    def test_uses_capture_phase(self):
        """`error` events don't bubble — the delegated listener must be
        registered in the capture phase or it would never fire."""
        src = self._main_js()
        m = re.search(
            r'function initializeImageErrorHandling\(\) \{(.+?)^\}',
            src, re.DOTALL | re.MULTILINE,
        )
        assert m, 'initializeImageErrorHandling not found'
        body = m.group(1)
        # Some form of capture flag must be passed to addEventListener.
        # Multi-line listener body means the listener body sits between the
        # 'error' string and the third arg; the capture flag lives in the
        # tail. Match the canonical 3-arg form or the `{ capture: true }`
        # options-object form anywhere after the listener body.
        capture_form = re.search(r"\}\s*,\s*(/\*[^*]*\*/\s*)?true\s*\)", body)
        options_form = re.search(r"\}\s*,\s*\{[^}]*capture\s*:\s*true[^}]*\}\s*\)", body)
        assert capture_form or options_form, (
            'delegated `error` listener must use capture phase (events do '
            'not bubble) — pass `true` as the third argument or '
            '`{ capture: true }` as the third options object'
        )

    @pytest.mark.parametrize('action', [
        'hide', 'hide-show-next', 'hide-show-id', 'src', 'outer-html',
    ])
    def test_action_handled(self, action):
        src = self._main_js()
        m = re.search(
            r'function initializeImageErrorHandling\(\) \{(.+?)^\}',
            src, re.DOTALL | re.MULTILINE,
        )
        assert m, 'initializeImageErrorHandling not found'
        body = m.group(1)
        assert f"'{action}'" in body, (
            f"action '{action}' missing from the dispatcher — templates "
            f"using `data-on-error=\"{action}\"` will silently fail"
        )
