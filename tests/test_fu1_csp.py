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

import pytest
import pathlib
import re

from tests import _util


REPO_ROOT = pathlib.Path(_util.REPO_ROOT)
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
        """Every inline `<script ...>` opening tag — whatever its other
        attributes — carries the per-request nonce. Widens the bare-`<script>`
        gate above to tags with attributes (`<script type=...>`), and replaces
        a hand-maintained count floor that drifted as templates changed.
        Tags with `src=` are external and need no nonce. Only tags that open
        a line are checked, so `<script>` written inside a JS comment or
        string is not mistaken for a tag."""
        tag_pattern = re.compile(r'^[ \t]*(<script\b[^>]*>)', re.MULTILINE)
        inline = 0
        offenders = []
        for path in _iter_template_files():
            for m in tag_pattern.finditer(path.read_text(encoding='utf-8')):
                tag = m.group(1)
                if 'src=' in tag:
                    continue
                inline += 1
                if 'nonce="{{ csp_nonce }}"' not in tag:
                    offenders.append(f"{path.relative_to(REPO_ROOT)}: {tag}")
        assert inline > 0, "found no inline <script> tags — the scan is broken"
        assert not offenders, (
            "Inline <script> tags must carry `nonce=\"{{ csp_nonce }}\"`:\n  "
            + "\n  ".join(offenders)
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


# ---------------------------------------------------------------------------
# No inline event handlers at all; delegated actions resolve
# ---------------------------------------------------------------------------

STATIC_JS_DIR = REPO_ROOT / 'static' / 'js'


def _iter_source_files():
    """Templates plus hand-written JS — the JS builds HTML strings too.
    Generated bundles are skipped; they are rebuilt from these."""
    js = [p for p in STATIC_JS_DIR.glob('*.js')
          if not p.name.endswith(('.bundle.js', '.min.js'))]
    return _iter_template_files() + js


class TestNoInlineEventHandlers:
    """An enforcing CSP blocks every inline `on<event>=` attribute. They use
    `data-on-<event>="fn"` instead (`main.js::initializeDelegatedActions`)."""

    # ` onclick="`, ` onclick='`, the escaped form inside a JS string, and
    # `setAttribute('onclick', ...)`.
    _ATTR = re.compile(r'''\son[a-z]+\s*=\s*(?:["']|\\["'])'''
                       r'''|setAttribute\(\s*["']on[a-z]+["']''')

    def test_no_inline_event_handler(self):
        offenders = []
        for path in _iter_source_files():
            for line_no, line in enumerate(
                    path.read_text(encoding='utf-8').splitlines(), 1):
                if self._ATTR.search(line):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{line_no}: {line.strip()[:120]}")
        assert not offenders, (
            "Inline event handlers break under an enforcing CSP; use "
            '`data-on-<event>="fn" data-args=\'[...]\'`:\n  '
            + "\n  ".join(offenders)
        )


class TestDelegatedActionsResolve:
    """Every `data-on-<event>` name must be a function the page can reach
    from `window`; a typo only shows as a console error at click time.
    build_js.py wraps each bundled static/js file in its own function, so a
    function declared there is reachable only through `window.X = `; a
    top-level `function X` in a template or an unbundled file is a global."""

    _ACTION = re.compile(r'data-on-(?!error\b)[a-z]+="([A-Za-z_$][\w$.]*)"')

    def _text(self, paths):
        return "\n".join(p.read_text(encoding='utf-8') for p in paths)

    def test_actions_found(self):
        text = self._text(_iter_source_files())
        assert len(set(self._ACTION.findall(text))) > 20, (
            "found almost no data-on-<event> actions — the scan is broken")

    def test_every_action_is_defined(self):
        import build_js
        bundled = set(build_js.CORE_ORDER) | set(build_js.GAMES_ORDER)
        everything = self._text(_iter_source_files())
        # Where a top-level `function X` is a global: page scripts and the
        # static/js files loaded on their own.
        globals_text = self._text(
            [p for p in _iter_source_files() if p.name not in bundled])
        missing = []
        for name in sorted(set(self._ACTION.findall(everything))):
            root, *members = name.split('.')
            r = re.escape(root)
            root_defined = root == 'window' or re.search(
                rf'window\.{r}\s*=|RetroDB\.{r}\s*=', everything) or re.search(
                rf'(?:^|\n)\s*(?:async\s+)?function\s+{r}\s*\(', globals_text)
            members_defined = all(
                re.search(rf'\b{re.escape(m)}\s*(?::|\(|=|,|\n\s*\}})', everything)
                for m in members)
            if not (root_defined and members_defined):
                missing.append(name)
        assert not missing, (
            "data-on-<event> names no window-reachable function (a static/js "
            "or page `const` function needs `window.X = X`):\n  "
            + "\n  ".join(missing))


class TestLiteralActionArgsAreJson:
    """A `data-args='[...]'` written out in full must parse; a stray
    backslash or quote only shows as a console error at click time.
    Values holding Jinja or `${...}` are built at render time and skipped."""

    _ARGS = re.compile(r"""data-args='([^']*)'""")

    def test_literal_args_parse(self):
        import json
        bad = []
        checked = 0
        for path in _iter_source_files():
            for m in self._ARGS.finditer(path.read_text(encoding='utf-8')):
                value = m.group(1)
                if '{{' in value or '${' in value or '{%' in value:
                    continue
                checked += 1
                try:
                    assert isinstance(json.loads(value), list)
                except (ValueError, AssertionError):
                    bad.append(f"{path.relative_to(REPO_ROOT)}: {value}")
        assert checked > 20, "found almost no literal data-args — the scan is broken"
        assert not bad, "data-args is not a JSON array:\n  " + "\n  ".join(bad)


class TestDelegatedActionDispatcher:
    def test_dispatcher_wired_in_capture_phase(self):
        src = (STATIC_JS_DIR / 'main.js').read_text(encoding='utf-8')
        assert 'initializeDelegatedActions();' in src
        m = re.search(r'function initializeDelegatedActions\(\) \{(.+?)^\}',
                      src, re.DOTALL | re.MULTILINE)
        assert m and re.search(r'\}\s*,\s*/\*[^*]*\*/\s*true\s*\)', m.group(1))
