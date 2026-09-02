# =============================================================================
# Pass 59.10-59.18 — build / packaging / release defects
# =============================================================================
# Regression pins for the build-and-install group. Most of these are
# file-on-disk invariants (what a launcher invokes, what a zip carries), so
# the tests are source-grep or in-process-collector style — the artifacts they
# guard take minutes to build and cannot be produced on every CI run.
# =============================================================================

import os
import pathlib
import re
import shutil
import subprocess
import sys

import pytest

from tests._util import REPO_ROOT as _REPO_ROOT

sys.path.insert(0, _REPO_ROOT)


def _read(*parts):
    with open(os.path.join(_REPO_ROOT, *parts), encoding='utf-8') as fh:
        return fh.read()


def _code(src):
    """Shell/batch source with whole-line comments dropped.

    These tests grep for what a launcher *invokes*; a comment saying what it
    deliberately no longer invokes must not read as the invocation.
    """
    return '\n'.join(line for line in src.splitlines()
                     if not line.lstrip().startswith(('#', 'REM ', 'REM\t')))


# -----------------------------------------------------------------------------
# 59.10 — the Standalone zip must ship launchers that run the binary
# -----------------------------------------------------------------------------
class TestPass59_10StandaloneLaunchers:
    """The bundle has a baked-in Python runtime and no .py files on disk, so a
    launcher that runs `python3 app.py` (which is what the SOURCE launchers at
    the repo root do) cannot start it."""

    STANDALONE = ('start.sh', 'start.command', 'start.bat')

    @pytest.mark.parametrize('name', STANDALONE)
    def test_standalone_launcher_exists(self, name):
        assert os.path.isfile(os.path.join(_REPO_ROOT, 'packaging', 'standalone', name))

    @pytest.mark.parametrize('name', STANDALONE)
    def test_standalone_launcher_never_invokes_python(self, name):
        code = _code(_read('packaging', 'standalone', name))
        for forbidden in ('app.py', 'server_port.py', 'build_css.py',
                          'python3', 'requirements.txt'):
            assert forbidden not in code, f'{name} reaches for {forbidden}'

    @pytest.mark.parametrize('name', STANDALONE)
    def test_standalone_launcher_runs_the_binary(self, name):
        assert 'retrodb' in _read('packaging', 'standalone', name)

    def test_build_standalone_ships_them(self):
        """build_standalone must take the launcher from packaging/standalone/,
        not the repo root."""
        src = _read('build_dist.py')
        body = src[src.index('def build_standalone'):src.index('def main(')]
        assert 'packaging/standalone/' in body

    def test_frozen_build_opens_the_browser(self):
        """Nothing else in the bundle can: only the server knows the resolved
        port, and the standalone launcher must not run Python to ask."""
        src = _read('app.py')
        assert "getattr(sys, 'frozen', False)" in src
        assert 'webbrowser.open' in src


# -----------------------------------------------------------------------------
# 59.11 — the shipped .desktop must be substituted somewhere
# -----------------------------------------------------------------------------
class TestPass59_11DesktopLauncher:

    def test_template_still_has_placeholders(self):
        """Guards the test below: the template is a template on purpose."""
        src = _read('packaging', 'RetroDB.desktop')
        assert '__EXEC__' in src and '__ICON__' in src

    def test_installer_ships_in_the_linux_bundle(self):
        src = _read('build_dist.py')
        body = src[src.index('def build_standalone'):src.index('def main(')]
        assert 'install-launcher.sh' in body

    @pytest.mark.skipif(shutil.which('bash') is None, reason='bash not available')
    def test_installer_substitutes_both_placeholders(self, tmp_path, monkeypatch):
        """Run the shipped installer against a fake extracted bundle and read
        back the .desktop it wrote — the placeholders must be gone."""
        bundle = tmp_path / 'RetroDB-Standalone'
        (bundle / 'packaging' / 'icons').mkdir(parents=True)
        shutil.copy(os.path.join(_REPO_ROOT, 'packaging', 'RetroDB.desktop'),
                    bundle / 'packaging' / 'RetroDB.desktop')
        (bundle / 'packaging' / 'icons' / 'retrodb-256.png').write_bytes(b'\x89PNG')
        (bundle / 'retrodb').write_text('#!/bin/sh\n')
        (bundle / 'retrodb').chmod(0o755)
        shutil.copy(
            os.path.join(_REPO_ROOT, 'packaging', 'standalone', 'install-launcher.sh'),
            bundle / 'install-launcher.sh')

        home = tmp_path / 'home'
        home.mkdir()
        env = dict(os.environ, HOME=str(home))
        env.pop('XDG_DATA_HOME', None)
        result = subprocess.run(['bash', str(bundle / 'install-launcher.sh')],
                                capture_output=True, text=True, env=env)
        assert result.returncode == 0, result.stderr

        written = (home / '.local' / 'share' / 'applications'
                   / 'RetroDB.desktop').read_text()
        assert '__EXEC__' not in written and '__ICON__' not in written
        assert f'Exec={bundle / "retrodb"}' in written
        assert f'Icon={bundle / "packaging" / "icons" / "retrodb-256.png"}' in written


# -----------------------------------------------------------------------------
# 59.12 — the source launchers must install via the hashed lockfile
# -----------------------------------------------------------------------------
class TestPass59_12LauncherInstallPath:
    """installer_core.select_pip_args prefers `--require-hashes -r
    requirements.lock`. A launcher running pip by hand bypassed it, and
    applied --break-system-packages unconditionally rather than as pip_install's
    PEP 668 retry."""

    LAUNCHERS = ('start.sh', 'start.command', 'start.bat')

    @pytest.mark.parametrize('name', LAUNCHERS)
    def test_no_hand_rolled_pip_install(self, name):
        src = _read(name)
        # Comments explain what was removed; strip them before grepping.
        code = '\n'.join(
            line for line in src.splitlines()
            if not line.lstrip().startswith(('#', 'REM ')))
        assert not re.search(r'pip\s+install', code), \
            f'{name} still installs dependencies by hand'

    @pytest.mark.parametrize('name', LAUNCHERS)
    def test_delegates_to_the_installer(self, name):
        assert 'install.py' in _read(name)

    def test_installer_still_prefers_the_lockfile(self):
        """The delegation is only worth anything if install.py's path is the
        hashed one."""
        import installer_core
        args, source = installer_core.select_pip_args(_REPO_ROOT)
        assert source == 'lock'
        assert '--require-hashes' in args


# -----------------------------------------------------------------------------
# 59.13 — the source ZIP is enumerated from git, not from a deny-list walk
# -----------------------------------------------------------------------------
class TestPass59_13SourceZipEnumeration:

    def _collected(self):
        import build_dist
        return {p.replace(os.sep, '/')
                for p, _ in build_dist.collect_files(_REPO_ROOT, set())}

    @pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
    def test_untracked_audit_output_never_ships(self):
        """audit_rule_quality.json is gitignored maintainer telemetry sitting
        at the repo root — not hidden, no excluded extension, and absent from
        EXCLUDE_FILES, so the old filesystem walk shipped it."""
        assert 'audit_rule_quality.json' not in self._collected()

    @pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
    def test_every_collected_path_is_tracked(self):
        tracked = subprocess.run(
            ['git', '-C', _REPO_ROOT, 'ls-files', '-z'],
            capture_output=True, check=True).stdout.decode().split('\0')
        tracked = {p for p in tracked if p}
        assert self._collected() <= tracked

    def test_the_deny_lists_still_apply(self):
        """git ls-files is the allow-list; the deny-lists still remove the
        tracked-but-maintainer-only files."""
        collected = self._collected()
        assert 'config.py' not in collected
        assert '.ants_review_falsepos.jsonl' not in collected
        assert not any(p.startswith('.claude/') for p in collected)

    def test_the_files_the_app_needs_still_ship(self):
        collected = self._collected()
        for required in ('app.py', 'config.example.py', 'requirements.lock',
                         'static/css/main.min.css', 'static/js/core.bundle.js',
                         'static/js/games.bundle.js'):
            assert required in collected, f'{required} dropped out of the ZIP'
        assert any(p.endswith('.mo') for p in collected), 'no compiled catalogs'

    def test_falls_back_when_git_is_unavailable(self, monkeypatch):
        import build_dist
        monkeypatch.setattr(build_dist, '_tracked_files', lambda base: None)
        walked = {p.replace(os.sep, '/')
                  for p, _ in build_dist.collect_files(_REPO_ROOT, set())}
        assert 'app.py' in walked


# -----------------------------------------------------------------------------
# 59.14 — settings must not re-import app.py by name
# -----------------------------------------------------------------------------
class TestPass59_14EntryModuleLookup:
    """`importlib.import_module('app')` raises ModuleNotFoundError in a
    PyInstaller bundle (app.py is the entry script, compiled into the PYZ as
    __main__) and builds a duplicate Flask app in a `python app.py` install."""

    def test_no_import_module_app(self):
        src = _read('routes', 'settings.py')
        assert 'import importlib' not in src
        assert '_entry_attr' in src

    def test_resolves_when_app_py_is_main(self, monkeypatch):
        import types
        import routes.settings as rs

        sentinel = types.ModuleType('__main__')
        sentinel.get_stats = lambda: {'total_games': 7}
        monkeypatch.delitem(sys.modules, 'app', raising=False)
        monkeypatch.setitem(sys.modules, '__main__', sentinel)
        assert rs.get_stats() == {'total_games': 7}

    def test_prefers_app_over_main(self, monkeypatch):
        import types
        import routes.settings as rs

        as_app = types.ModuleType('app')
        as_app.get_api_status = lambda: {'database': True}
        monkeypatch.setitem(sys.modules, 'app', as_app)
        assert rs.get_api_status() == {'database': True}

    def test_raises_a_named_error_when_absent(self, monkeypatch):
        import types
        import routes.settings as rs

        monkeypatch.delitem(sys.modules, 'app', raising=False)
        monkeypatch.setitem(sys.modules, '__main__', types.ModuleType('__main__'))
        with pytest.raises(RuntimeError, match='get_stats'):
            rs.get_stats()


# -----------------------------------------------------------------------------
# 59.15 / 59.16 — the JS i18n scan and its freshness check
# -----------------------------------------------------------------------------
class TestPass59_15JsI18nScope:

    def test_every_hand_written_source_is_scanned(self):
        import build_js
        js_dir = build_js.get_js_dir()
        on_disk = {p.name for p in js_dir.glob('*.js')
                   if not p.name.endswith('.bundle.js')}
        assert set(build_js.js_i18n_sources(js_dir)) == on_disk

    def test_generated_bundles_are_not_scanned(self):
        import build_js
        names = build_js.js_i18n_sources(build_js.get_js_dir())
        assert not any(n.endswith('.bundle.js') for n in names)

    def test_the_ci_gate_uses_the_same_collector(self):
        """The gate compared a blind scan against a blind manifest and passed.
        Sharing the collector is what makes widening it fix both."""
        import build_js
        import scripts.check_i18n_fresh as gate
        assert gate.build_js.collect_js_i18n_keys is build_js.collect_js_i18n_keys

    @pytest.mark.parametrize('name', ('launch-indicator.js', 'game-launch.js',
                                      'emulators-settings.js'))
    def test_previously_unscanned_files_now_contribute_keys(self, name):
        import build_js
        src = (build_js.get_js_dir() / name).read_text(encoding='utf-8')
        keys = build_js.scan_t_keys(src)
        assert keys, f'{name} has no t() calls — its strings are still hardcoded'
        from services.js_i18n_strings import JS_I18N_KEYS
        assert keys <= set(JS_I18N_KEYS)


class TestPass59_16FreshnessScope:

    def test_freshness_watches_the_i18n_sources(self, monkeypatch, tmp_path):
        """A t() added to a page-specific file must invalidate the build.
        Iterating BUNDLES alone reported "up-to-date" and main() returned
        before generate_js_i18n_manifest ever ran."""
        import build_js

        # Sandbox the whole thing — sources, bundles and the manifest — so the
        # real tree is untouched and the mtimes are set, not inherited.
        work = tmp_path / 'js'
        shutil.copytree(build_js.get_js_dir(), work)
        manifest = tmp_path / 'js_i18n_strings.py'
        manifest.write_text('JS_I18N_KEYS = []\n')
        monkeypatch.setattr(build_js, 'get_js_dir', lambda: work)
        monkeypatch.setattr(build_js, 'js_i18n_manifest_path', lambda: manifest)

        # Outputs newer than every input, including build_js.py itself.
        newest = max(p.stat().st_mtime for p in list(work.iterdir()) + [
            pathlib.Path(build_js.__file__)])
        for out in [work / name for name, _ in build_js.BUNDLES] + [manifest]:
            os.utime(out, (newest + 10, newest + 10))
        assert build_js.is_output_fresh(), 'baseline should start fresh'

        page_specific = work / 'settings-page.js'
        assert page_specific.exists(), 'page-specific source missing from sandbox'
        os.utime(page_specific, (newest + 20, newest + 20))  # as an edit would
        assert not build_js.is_output_fresh()


# -----------------------------------------------------------------------------
# 59.17 — the AMD ROCm override must not fire on every Linux machine
# -----------------------------------------------------------------------------
class TestPass59_17RocmOverrideGated:
    """gfx1032 is the maintainer's card. Forcing its ISA on a different AMD
    architecture makes the ESRGAN upscaler hang or crash rather than fail
    cleanly."""

    def test_not_exported_unconditionally(self):
        for line in _read('start.sh').splitlines():
            # An unindented export is a top-level one; the gated form sits
            # inside an `if`, so it is indented.
            if line.startswith('export HSA_OVERRIDE_GFX_VERSION'):
                pytest.fail('HSA_OVERRIDE_GFX_VERSION is exported at top level')

    def test_gated_on_the_card_and_the_environment(self):
        src = _read('start.sh')
        assert 'HSA_OVERRIDE_GFX_VERSION:-' in src, 'an explicit value must win'
        assert 'gfx1032' in src, 'the override must be gated on the card'


# -----------------------------------------------------------------------------
# 59.18 — the release script must refuse a stale local tag
# -----------------------------------------------------------------------------
class TestPass59_18StaleTagRefused:

    def test_tag_creation_failure_is_not_swallowed(self):
        src = _read('release-standalone.sh')
        assert 'git tag -a "$TAG" -m "RetroDB $TAG" 2>/dev/null || true' not in src

    def test_existing_local_tag_is_verified_against_head(self):
        src = _read('release-standalone.sh')
        assert 'rev-parse -q --verify "refs/tags/$TAG' in src
        assert 'git rev-parse HEAD' in src

    @pytest.mark.skipif(shutil.which('git') is None, reason='git not available')
    def test_the_guard_rejects_a_tag_at_an_older_commit(self, tmp_path):
        """Exercise the comparison itself in a throwaway repo, so the pin is
        about behaviour rather than the spelling of a grep."""
        repo = tmp_path / 'repo'
        repo.mkdir()

        def git(*args, **kw):
            return subprocess.run(['git', '-C', str(repo), *args],
                                  capture_output=True, text=True, check=True, **kw)

        git('init', '-q')
        git('config', 'user.email', 'test@example.invalid')
        git('config', 'user.name', 'Test')
        (repo / 'a').write_text('1')
        git('add', 'a')
        git('commit', '-qm', 'first')
        git('tag', '-a', 'v1.0.0', '-m', 'stale')
        (repo / 'a').write_text('2')
        git('commit', '-qam', 'second')

        tagged = git('rev-parse', '-q', '--verify', 'refs/tags/v1.0.0^{commit}').stdout.strip()
        head = git('rev-parse', 'HEAD').stdout.strip()
        assert tagged != head, 'the stale tag must not resolve to HEAD'
