# =============================================================================
# v3.6.6 — HLTB endpoint pin (whack-a-mole rename history)
# =============================================================================
# HowLongToBeat keeps renaming their search API endpoint:
#   pre-2026-04   /api/finder        — 404
#   2026-04..05   /api/find/init     — 404 (renamed ~2026-05)
#   2026-05+      /api/bleed/init    — current
#
# Diagnosed on 2026-05-17 from `scraper.base_scraper - WARNING - HTTP GET
# failed: 404 - https://howlongtobeat.com/api/find/init?t=…` in the user's
# server logs. Confirmed the new endpoint by greping HLTB's own Next.js JS
# chunks for `api/bleed` and verified the init + search response shape with a
# live curl probe.
#
# This test pins the current URL at the source level. Network-mocking tests
# in test_hltb_alt_titles already stub _search_hltb wholesale, so they don't
# catch URL drift. This source-level check fails loudly the next time HLTB
# renames the endpoint — turning a silent "lookup never works" regression
# into a 1-test-failure CI signal pointing at the right line.
# =============================================================================

from __future__ import annotations

import ast
import os
import sys


_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def _strip_docstrings(src: str) -> str:
    """Return source with every docstring node replaced by a blank line.

    Used by `test_no_residual_stale_paths` so stale-URL strings that appear
    inside module / class / function docstrings (the rename-history block in
    `hltb_lookup.py`) don't trip the assertion. Line-by-line triple-quote
    detection couldn't see the body lines of multi-line docstrings — the AST
    walk catches the whole node.
    """
    tree = ast.parse(src)
    blanks: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, 'body', None)
            if not body:
                continue
            first = body[0]
            if (
                isinstance(first, ast.Expr)
                and isinstance(first.value, ast.Constant)
                and isinstance(first.value.value, str)
            ):
                for ln in range(first.lineno, first.end_lineno + 1):
                    blanks.add(ln)
    out = []
    for idx, line in enumerate(src.splitlines(), start=1):
        out.append('' if idx in blanks else line)
    return '\n'.join(out)


class TestHLTBEndpointPin:
    """The init + search URLs must point at /api/bleed. When HLTB renames
    again, update both the constant and the rename-history comment in
    scraper/hltb_lookup.py:_get_auth_token."""

    @staticmethod
    def _read_source():
        path = os.path.join(_REPO_ROOT, 'scraper', 'hltb_lookup.py')
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_init_url_points_to_bleed_init(self):
        src = self._read_source()
        assert '/api/bleed/init' in src, (
            'scraper/hltb_lookup.py must call /api/bleed/init — HLTB renamed '
            'the init endpoint around 2026-05.  If this fails again, probe '
            'https://howlongtobeat.com/api/<NEW>/init?t=<ms> and update the '
            'URL + rename-history comment in _get_auth_token.'
        )

    def test_search_url_points_to_bleed(self):
        src = self._read_source()
        # Two POSTs to /api/bleed — initial search + token-refresh retry.
        assert src.count('"/api/bleed"') + src.count("'/api/bleed'") + src.count('/api/bleed') >= 3, (
            'scraper/hltb_lookup.py must POST to /api/bleed for the search '
            'call (and again in the token-expired retry branch). The init '
            'and search endpoints rename in lockstep, so updating one and '
            'not the other will 404 the search and silently return no hits.'
        )

    def test_no_residual_stale_paths(self):
        """The whole module must not still contain a *live* reference to a
        renamed endpoint. Comments inside the rename-history block are
        allowed (they're documentation), but no f-string / URL literal
        should reach /api/find or /api/finder."""
        src = self._read_source()
        # Strip docstrings via AST so multi-line documentation lines inside
        # the rename-history block don't false-trigger the check. Comments
        # still need a per-line skip.
        src_no_docstrings = _strip_docstrings(src)
        for line in src_no_docstrings.splitlines():
            stripped = line.strip()
            if stripped.startswith('#'):
                continue  # comment — rename-history allowed
            assert '/api/find/' not in line and '/api/finder' not in line, (
                f'Stale HLTB URL on live line:\n  {line!r}\n'
                f'Move it to the rename-history comment block or delete it.'
            )
