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
        with `--require-hashes` so a tampered wheel fails the install.
        Pass 38.3 — both installers now route through
        `installer_core.select_pip_args`; assert that helper emits
        `--require-hashes` against the real lockfile and that both
        installers import the shared module."""
        import installer_core
        repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        args, source = installer_core.select_pip_args(repo_root)
        assert source == 'lock', (
            f"installer_core.select_pip_args returned source={source!r} "
            f"against the repo root — expected 'lock' (the committed "
            f"requirements.lock should be the chosen path)."
        )
        assert '--require-hashes' in args, (
            f"installer_core.select_pip_args must emit --require-hashes "
            f"when the lockfile is present (got args={args!r}). MITM-"
            f"tampered wheels would otherwise pass the install (Pass 39.4)."
        )
        cli_src = self._read(self.INSTALL_CLI)
        gui_src = self._read(self.INSTALL_GUI)
        for name, src in (('install.py', cli_src), ('install_gui.py', gui_src)):
            assert 'installer_core' in src, (
                f"{name} must import the shared installer_core module so "
                f"it picks up the --require-hashes contract from "
                f"select_pip_args (Pass 38.3 + 39.4)."
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


# -----------------------------------------------------------------------------
# 39.5 — Dependabot lockfile auto-regeneration workflow
# -----------------------------------------------------------------------------
class TestPass39_5DependabotLockfileWorkflow:
    """Pass 39.5 closes the loop opened by Pass 39.4: every Dependabot bump
    of requirements.txt would otherwise fail the CI lockfile-drift check
    until a human regenerated requirements.lock by hand. The new workflow
    `.github/workflows/dependabot-lockfile.yml` does that automatically
    against the Dependabot PR branch."""

    WORKFLOW = os.path.join(
        _REPO_ROOT, '.github', 'workflows', 'dependabot-lockfile.yml'
    )

    def test_workflow_file_exists(self):
        assert os.path.exists(self.WORKFLOW), (
            "Pass 39.5 expects .github/workflows/dependabot-lockfile.yml "
            "to exist — Dependabot bumps would otherwise leave the lockfile "
            "out of sync until a human regenerates it."
        )

    def test_workflow_is_parseable_yaml_with_correct_shape(self):
        """The workflow must trigger only on PRs that touch requirements.txt,
        guard execution to the dependabot[bot] actor, request the
        write-permissions needed to push back, and run pip-compile with
        --generate-hashes (matches the lockfile recipe pinned in 39.4)."""
        import yaml
        with open(self.WORKFLOW, encoding='utf-8') as f:
            cfg = yaml.safe_load(f)

        # Path-scoped trigger on requirements.txt change.
        # PyYAML rewrites the bare `on` key to True (boolean key) — accept
        # both the unparsed string and the boolean form.
        triggers = cfg.get('on') or cfg.get(True)
        assert triggers, "workflow must declare triggers under `on:`"
        pr = triggers.get('pull_request', {})
        assert 'requirements.txt' in (pr.get('paths') or []), (
            "workflow must scope to PRs touching requirements.txt"
        )

        # Only run for Dependabot-authored PRs.
        regen_job = cfg.get('jobs', {}).get('regenerate-lockfile', {})
        assert regen_job, "workflow must define a `regenerate-lockfile` job"
        assert "dependabot[bot]" in str(regen_job.get('if', '')), (
            "workflow must guard the regen job to dependabot[bot] actor"
        )

        # Permissions narrow but include contents:write for the push.
        perms = cfg.get('permissions', {})
        assert perms.get('contents') == 'write', (
            "workflow must request contents:write so it can push the "
            "regenerated lockfile back to the Dependabot PR branch"
        )

    def test_pip_compile_invocation_uses_generate_hashes(self):
        """Without --generate-hashes the auto-regen would land an
        unhashed lockfile that breaks `pip install --require-hashes` in
        the installers (Pass 39.4)."""
        with open(self.WORKFLOW, encoding='utf-8') as f:
            src = f.read()
        compile_lines = [
            ln for ln in src.splitlines() if 'pip-compile' in ln
        ]
        assert compile_lines, (
            "workflow has no pip-compile invocation — update this test"
        )
        # At least one of the pip-compile lines must carry --generate-hashes
        # (the actual run command may span multiple continuation lines).
        assert '--generate-hashes' in src, (
            "workflow's pip-compile invocation must include --generate-hashes"
        )
