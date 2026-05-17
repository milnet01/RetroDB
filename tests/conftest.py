"""Top-level pytest configuration."""

from __future__ import annotations

# Force Qt's offscreen QPA platform before anything imports QApplication.
# RetroDB is a Flask web app and doesn't pull in Qt today, but adding
# the safe default here makes it impossible for a future Qt-using
# test (or a transitive import that creates a QApplication at import
# time) to flash a real top-level window onto the desktop hosting the
# test runner. `setdefault` lets a CI override
# (e.g. QT_QPA_PLATFORM=minimal) still win.
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# Re-export shared utilities so test files can `from tests._util import ...`
# without each one re-computing REPO_ROOT and inserting sys.path.
from tests._util import REPO_ROOT, read_source, slice_function, count_except_blocks  # noqa: E402,F401
