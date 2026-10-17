# =============================================================================
# v3.6.6 — HLTB endpoint pin (whack-a-mole rename history)
# =============================================================================
# HowLongToBeat keeps renaming their search API endpoint:
#   pre-2026-04   /api/finder        — 404
#   2026-04..05   /api/find/init     — 404 (renamed ~2026-05)
#   2026-05..07   /api/bleed/init    — 404 (renamed again 2026-07/09)
#   2026-09+      /api/search/site/init — current; the search filters also
#                 changed shape to {'mode': 'include', 'values': [...]} and
#                 the old string/rangeYear filters are silently ignored
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
import re

from tests._util import REPO_ROOT as _REPO_ROOT


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
    """The init + search URLs must point at /api/search/site. When HLTB renames
    again, update both the constant and the rename-history comment in
    scraper/hltb_lookup.py:_get_auth_token."""

    @staticmethod
    def _read_source():
        path = os.path.join(_REPO_ROOT, 'scraper', 'hltb_lookup.py')
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_init_url_points_to_search_site_init(self):
        src = self._read_source()
        assert '/api/search/site/init' in src, (
            'scraper/hltb_lookup.py must call /api/search/site/init — HLTB renamed '
            'the init endpoint again in 2026.  If this fails again, probe '
            'https://howlongtobeat.com/api/<NEW>/init?t=<ms> and update the '
            'URL + rename-history comment in _get_auth_token.'
        )

    def test_search_url_points_to_search_site(self):
        src = self._read_source()
        # Two POSTs to /api/search/site — initial search + token-refresh retry.
        # Strict regex: match `/api/bleed` followed immediately by a closing
        # quote (single or double). That excludes `/api/bleed/init` (which
        # would have a `/` after `bleed`) — the bug the looser substring
        # count had: every `/api/bleed/init` line incremented the bare
        # `src.count('/api/bleed')` total, so a file with zero search calls
        # and three init lines would still pass.
        search_full_path_hits = re.findall(r"/api/search/site['\"]", src)
        assert len(search_full_path_hits) >= 2, (
            'scraper/hltb_lookup.py must POST to /api/search/site for the search '
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
            assert ('/api/find/' not in line and '/api/finder' not in line
                    and '/api/bleed' not in line), (
                f'Stale HLTB URL on live line:\n  {line!r}\n'
                f'Move it to the rename-history comment block or delete it.'
            )


class TestHLTBSearchFilters:
    """HLTB now reads filters as {'mode': 'include', 'values': [...]}. The old
    string platform and rangeYear were silently ignored (probe 2026-10-17:
    "Halo 3" on NES still returned Halo 3), so the platform-filtered search
    step matched nothing extra."""

    def _payload(self, monkeypatch, **kw):
        import scraper.hltb_lookup as h

        class _Resp:
            status_code = 200
            def __init__(self, body): self._b = body
            def json(self): return self._b

        sent = {}
        monkeypatch.setattr(h, '_auth_token', None)
        monkeypatch.setattr(h, 'http_get', lambda *a, **k: _Resp({'token': 't'}))
        def fake_post(url, headers=None, json_data=None, timeout=None):
            sent['url'], sent['body'] = url, json_data
            return _Resp({'data': []})
        monkeypatch.setattr(h, 'http_post', fake_post)
        h._search_hltb('Halo 3', **kw)
        return sent

    def test_platform_and_year_use_include_filters(self, monkeypatch):
        sent = self._payload(monkeypatch, platform='Xbox 360', year=2007)
        games = sent['body']['searchOptions']['games']
        assert sent['url'].endswith('/api/search/site')
        assert games['platform'] == {'mode': 'include', 'values': ['Xbox 360']}
        assert games['year'] == {'mode': 'include', 'values': ['2007']}
        assert 'rangeYear' not in games

    def test_no_platform_or_year_sends_empty_filters(self, monkeypatch):
        games = self._payload(monkeypatch)['body']['searchOptions']['games']
        assert games['platform'] == {'mode': 'include', 'values': []}
        assert games['year'] == {'mode': 'include', 'values': []}
