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


def count_except_blocks(src: str, function_name: str) -> int:
    """Count `try/except` blocks inside the named function. Used by
    source-structure tests that want to verify error-handling shape
    without anchoring to a literal comment marker."""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
            return sum(1 for sub in ast.walk(node) if isinstance(sub, ast.Try))
    return 0
