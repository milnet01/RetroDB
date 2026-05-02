# =============================================================================
# Pass 39 — CI/supply-chain hardening (round 2)
# =============================================================================
# Regression pins for supply-chain controls landed in Pass 39 (CI workflow
# pinning, lockfile hash verification). Tests here are source-grep style
# because the contract is a file-on-disk invariant: lockfile shape, installer
# arguments, and the CI workflow's recompile recipe.
# =============================================================================

import os
import re
import sys

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


# -----------------------------------------------------------------------------
# 39.4 — requirements.lock with --generate-hashes + installers --require-hashes
# -----------------------------------------------------------------------------
class TestPass39_4LockfileHashes:
    """Pass 39.4 hardens the install path against MITM / PyPI tamper. The
    lockfile must carry SHA256 hashes for every pinned package, and the
    installers (CLI + GUI) must run `pip install --require-hashes` so an
    altered wheel is rejected at the wire. CI's drift check must also use
    --generate-hashes so its recompile stays comparable to the committed
    lockfile."""

    LOCKFILE = os.path.join(_REPO_ROOT, 'requirements.lock')
    INSTALL_CLI = os.path.join(_REPO_ROOT, 'install.py')
    INSTALL_GUI = os.path.join(_REPO_ROOT, 'install_gui.py')
    CI_WORKFLOW = os.path.join(_REPO_ROOT, '.github', 'workflows', 'ci.yml')

    def _read(self, path):
        with open(path, encoding='utf-8') as f:
            return f.read()

    def test_every_pinned_package_carries_a_hash(self):
        """Every `name==version \\` line in requirements.lock must be
        followed by at least one `--hash=sha256:...` entry. A bare
        `name==version` (no hashes) means `pip install --require-hashes`
        would fail with "hashes required" — that's a contract break."""
        src = self._read(self.LOCKFILE)
        # Match "name==version \" with optional spaces, anchored at line start.
        pinned_lines = re.findall(
            r'^([a-zA-Z0-9_.\-]+==\S+)\s*\\\s*$',
            src,
            flags=re.MULTILINE,
        )
        assert pinned_lines, (
            "requirements.lock has no `name==version \\` entries — lockfile "
            "shape changed; update this test."
        )
        # Each pinned line should be followed (within a few lines) by at least
        # one --hash=sha256: line. Cheap structural check: the file should
        # contain at least as many `--hash=sha256:` lines as pinned packages.
        hash_count = src.count('--hash=sha256:')
        assert hash_count >= len(pinned_lines), (
            f"requirements.lock has {len(pinned_lines)} pinned packages but "
            f"only {hash_count} `--hash=sha256:` entries — at least one "
            f"package is missing hashes (re-run pip-compile --generate-hashes)."
        )

    def test_lockfile_header_records_generate_hashes_recipe(self):
        """pip-compile writes the regeneration command into the lockfile
        header. Pin that header carries `--generate-hashes` so a future
        pip-compile run without that flag is visible in the diff."""
        src = self._read(self.LOCKFILE)
        # Header is the first ~6 lines. Take a generous slice.
        header = src[:512]
        assert '--generate-hashes' in header, (
            "requirements.lock header should record `--generate-hashes` in "
            "its pip-compile recipe — regenerate with: "
            "pip-compile requirements.txt -o requirements.lock "
            "--strip-extras --generate-hashes"
        )

    def test_installers_use_require_hashes(self):
        """Both install.py and install_gui.py prefer the hashed lockfile
        with `--require-hashes` so a tampered wheel fails the install."""
        cli_src = self._read(self.INSTALL_CLI)
        gui_src = self._read(self.INSTALL_GUI)
        for name, src in (('install.py', cli_src), ('install_gui.py', gui_src)):
            assert "'--require-hashes'" in src or '"--require-hashes"' in src, (
                f"{name} must invoke pip with `--require-hashes` so MITM-"
                f"tampered wheels are rejected (Pass 39.4)"
            )
            assert 'requirements.lock' in src, (
                f"{name} must reference the hashed lockfile path"
            )

    def test_ci_drift_check_uses_generate_hashes(self):
        """The CI workflow's lockfile-drift step regenerates a fresh lock
        for diffing. It must use `--generate-hashes` so the regenerated
        lock is comparable to the committed one (which carries hashes).
        Otherwise the diff false-positives on every PR."""
        src = self._read(self.CI_WORKFLOW)
        # Grab the line containing `pip-compile` inside the drift step.
        compile_lines = [ln for ln in src.splitlines() if 'pip-compile' in ln and '/tmp/fresh.lock' in ln]
        assert compile_lines, (
            "ci.yml lockfile-drift step doesn't run pip-compile against "
            "/tmp/fresh.lock anymore — update this test."
        )
        for ln in compile_lines:
            assert '--generate-hashes' in ln, (
                f"ci.yml drift recompile must include --generate-hashes "
                f"(line: {ln.strip()})"
            )
