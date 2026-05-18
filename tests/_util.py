"""Shared utilities for the test suite.

Extracted during the 2026-05-17 test-audit fix-pass: ~15 test files were
copy-pasting `_REPO_ROOT = os.path.dirname(...)` + `sys.path.insert(0, ...)` +
`open(__file__).read()` boilerplate. Centralising those here lets the
source-grep tests share one read path and one function-body slicer.
"""

from __future__ import annotations

import ast
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)


def read_source(rel_path: str) -> str:
    """Return the text of <REPO_ROOT>/<rel_path>.

    Uses a context manager so the fd is closed even on read failure
    (replaces ~15 bare `open(...).read()` sites flagged by the audit).
    """
    full = os.path.join(REPO_ROOT, rel_path)
    with open(full, encoding="utf-8") as f:
        return f.read()


def read_settings_with_partials() -> str:
    """Return `templates/settings.html` concatenated with every
    `templates/_settings_tabs/*.html` partial.

    Pass 38.6 split the settings page into a thin shell that `{% include %}`s
    six tab partials. Source-grep tests that used to look for a string in
    `settings.html` keep working if they search the union — the string still
    lives in the rendered page, just in a different file on disk.
    """
    import glob
    parts = [read_source("templates/settings.html")]
    pattern = os.path.join(REPO_ROOT, "templates", "_settings_tabs", "*.html")
    for path in sorted(glob.glob(pattern)):
        with open(path, encoding="utf-8") as f:
            parts.append(f.read())
    return "\n".join(parts)


def read_module_source(mod) -> str:
    """Return the text of an already-imported module's source file.

    Convenience wrapper over `open(mod.__file__).read()` for the source-grep
    tests that hold a module reference rather than a relative path. Uses a
    context manager so the fd is closed even on read failure."""
    with open(mod.__file__, encoding="utf-8") as f:
        return f.read()


def slice_function(src: str, name: str) -> str:
    """Return the source text of the named top-level (or top-of-class) function.

    Walks the AST so docstrings and comments inside the function body are
    included but unrelated functions are not. Returns the empty string if the
    name is not found — callers should assert non-empty to fail loudly.
    """
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(src, node) or ""
    return ""


def js_method_body(src: str, method_name: str) -> str:
    """Slice the body of a JS function/method declared as `name(args) {`.

    JS isn't AST-parsed by `slice_function` (Python-only). This helper:
      1. Scans for occurrences of `<method_name>(`.
      2. For each, balances `()` to skip the parameter list (including
         `options = {}` defaults — that `{` is paren-scoped, not the body).
      3. If the next non-whitespace character after the matching `)` is
         `{`, that occurrence is a definition; otherwise it is a call
         (e.g. `this.renderLine(line);`) and we keep scanning.
      4. Balances `{}` from the body `{` to find the matching close.
    Returns text from the body `{` to the matching `}` (inclusive).

    Promoted from `tests/test_pass29_frontend.py::_js_method_body` so JS
    source-grep tests in other files can use it without cross-test imports
    (test-audit c-001 ISO finding) and without re-implementing the slice
    inline with hardcoded windows (test-audit c-004 MED). The call-vs-
    definition disambiguation was added when the renderLine() case
    surfaced a hit on `chunks.push(this.renderLine(line))` ahead of the
    actual definition.
    """
    needle = method_name + '('
    search_from = 0
    while True:
        idx = src.find(needle, search_from)
        if idx == -1:
            raise AssertionError(
                f"no `{method_name}(` declaration found in source"
            )
        paren_depth = 0
        i = idx + len(method_name)  # positioned at '('
        while i < len(src):
            ch = src[i]
            if ch == '(':
                paren_depth += 1
            elif ch == ')':
                paren_depth -= 1
                if paren_depth == 0:
                    i += 1
                    break
            i += 1
        else:
            raise AssertionError(
                f"unbalanced parens in JS method {method_name!r}"
            )
        # Skip whitespace and look for the body brace. If the next
        # non-whitespace char is `{`, this is a definition; otherwise
        # it's a call site (e.g. `foo(args);` or `x = foo(args).bar`).
        while i < len(src) and src[i] in ' \t\r\n':
            i += 1
        if i < len(src) and src[i] == '{':
            brace = i
            depth = 0
            for j in range(brace, len(src)):
                ch = src[j]
                if ch == '{':
                    depth += 1
                elif ch == '}':
                    depth -= 1
                    if depth == 0:
                        return src[brace:j + 1]
            raise AssertionError(
                f"unbalanced braces in JS method {method_name!r}"
            )
        # Not a definition — keep scanning past this match.
        search_from = idx + len(needle)


def count_except_blocks(src: str, function_name: str) -> int:
    """Count `try/except` blocks inside the named function. Used by
    source-structure tests that want to verify error-handling shape
    without anchoring to a literal comment marker."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return sum(1 for sub in ast.walk(node) if isinstance(sub, ast.Try))
    return 0
