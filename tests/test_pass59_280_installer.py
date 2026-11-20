# =============================================================================
# PASS-59-280 — installer safety
# =============================================================================
# A system Python that forbids pip installs (PEP 668) gets RetroDB's own
# Python folder instead of a silent --break-system-packages; settings
# templates are copied owner-only; Pillow comes only from the locked install;
# the installers name the real port.
# =============================================================================

import os
import stat
import subprocess
import sys
from unittest import mock

import pytest

from tests._util import REPO_ROOT

sys.path.insert(0, REPO_ROOT)

import installer_core  # noqa: E402


def _read(name):
    with open(os.path.join(REPO_ROOT, name), encoding='utf-8') as fh:
        return fh.read()


class _Runs:
    """Records subprocess.run calls; answers each with the next reply."""

    def __init__(self, *replies):
        self.calls, self.replies = [], list(replies)

    def __call__(self, cmd, **kwargs):
        self.calls.append(list(cmd))
        rc, err = self.replies.pop(0)
        return subprocess.CompletedProcess(cmd, rc, '', err)


REFUSED = (1, 'error: externally-managed-environment')


class TestPipInstall:
    def test_a_refusal_is_returned_not_overridden(self, monkeypatch):
        runs = _Runs(REFUSED)
        monkeypatch.setattr(installer_core.subprocess, 'run', runs)
        result = installer_core.pip_install(['-r', 'x'], python='/p/python')
        assert result.returncode == 1
        assert len(runs.calls) == 1
        assert runs.calls[0][0] == '/p/python'
        assert '--break-system-packages' not in runs.calls[0]

    def test_the_updater_may_still_override(self, monkeypatch):
        runs = _Runs(REFUSED, (0, ''))
        monkeypatch.setattr(installer_core.subprocess, 'run', runs)
        result = installer_core.pip_install(['-r', 'x'], system_ok=True)
        assert result.returncode == 0
        assert runs.calls[1][-1] == '--break-system-packages'

    def test_updater_asks_for_the_override(self, monkeypatch, tmp_path):
        import updater_apply
        seen = {}

        class Core:
            @staticmethod
            def select_pip_args(base):
                return ['-r', 'lock'], 'lock'

            @staticmethod
            def pip_install(args, base, quiet=False, system_ok=False):
                seen['system_ok'] = system_ok
                return subprocess.CompletedProcess(args, 0, '', '')

        monkeypatch.setattr(updater_apply, '_load_installer_core', lambda d: Core)
        updater_apply.install_dependencies({'install_dir': str(tmp_path)}, lambda m: None)
        assert seen == {'system_ok': True}


class TestChoosePython:
    def test_existing_folder_wins(self, tmp_path):
        venv = installer_core.venv_python(str(tmp_path))
        os.makedirs(os.path.dirname(venv))
        open(venv, 'w').close()
        assert installer_core.choose_python(str(tmp_path)) == (venv, 'venv', '')

    def test_an_open_python_is_used_as_is(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer_core, 'externally_managed', lambda: False)
        assert installer_core.choose_python(str(tmp_path)) == (sys.executable, 'system', '')

    def test_a_protected_python_gets_a_folder(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer_core, 'externally_managed', lambda: True)
        venv = installer_core.venv_python(str(tmp_path))

        def fake_run(cmd, **kwargs):
            assert cmd[1:3] == ['-m', 'venv']
            assert cmd[3] == os.path.join(str(tmp_path), '.venv')
            os.makedirs(os.path.dirname(venv))
            open(venv, 'w').close()
            return subprocess.CompletedProcess(cmd, 0, '', '')

        monkeypatch.setattr(installer_core.subprocess, 'run', fake_run)
        assert installer_core.choose_python(str(tmp_path)) == (venv, 'venv-created', '')

    def test_a_folder_that_cannot_be_made_says_why(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer_core, 'externally_managed', lambda: True)
        monkeypatch.setattr(installer_core.subprocess, 'run', lambda cmd, **k:
                            subprocess.CompletedProcess(cmd, 1, '', 'ensurepip is not available'))
        python, how, output = installer_core.choose_python(str(tmp_path))
        assert (python, how) == (None, 'failed')
        assert 'ensurepip' in output

    def test_marker_file_decides(self, tmp_path, monkeypatch):
        monkeypatch.setattr(installer_core.sys, 'prefix', installer_core.sys.base_prefix)
        monkeypatch.setattr(installer_core.sysconfig, 'get_path', lambda name: str(tmp_path))
        assert not installer_core.externally_managed()
        (tmp_path / 'EXTERNALLY-MANAGED').write_text('[externally-managed]\n')
        assert installer_core.externally_managed()

    def test_inside_a_venv_nothing_is_protected(self, monkeypatch):
        monkeypatch.setattr(installer_core.sys, 'prefix', '/somewhere/.venv')
        assert not installer_core.externally_managed()


@pytest.mark.skipif(os.name == 'nt', reason='POSIX file modes')
class TestCopyPrivate:
    def test_owner_only(self, tmp_path):
        src = tmp_path / 'config.example.py'
        src.write_text('SECRET = 1\n')
        dst = tmp_path / 'sub' / 'config.py'
        assert installer_core.copy_private(str(src), str(dst))
        assert dst.read_text() == 'SECRET = 1\n'
        assert stat.S_IMODE(dst.stat().st_mode) == 0o600

    def test_never_replaces(self, tmp_path):
        src = tmp_path / 'a'
        src.write_text('new')
        dst = tmp_path / 'b'
        dst.write_text('mine')
        assert not installer_core.copy_private(str(src), str(dst))
        assert dst.read_text() == 'mine'

    def test_never_follows_a_link(self, tmp_path):
        src = tmp_path / 'a'
        src.write_text('new')
        target = tmp_path / 'elsewhere'
        dst = tmp_path / 'b'
        dst.symlink_to(target)
        assert not installer_core.copy_private(str(src), str(dst))
        assert not target.exists()


def test_server_url_reads_the_port(monkeypatch):
    monkeypatch.setenv('PORT', '5123')
    assert installer_core.server_url(REPO_ROOT) == 'http://localhost:5123'


def test_opensuse_is_named(monkeypatch):
    text = 'NAME="openSUSE Tumbleweed"\nID="opensuse-tumbleweed"\nID_LIKE="opensuse suse"\n'
    monkeypatch.setattr(installer_core.sys, 'platform', 'linux')
    with mock.patch('builtins.open', mock.mock_open(read_data=text)):
        assert installer_core.detect_distro() == 'suse'


@pytest.mark.parametrize('name', ['install.py', 'install_gui.py'])
def test_no_unlocked_pillow_install(name):
    assert "pip_install(['Pillow']" not in _read(name)


@pytest.mark.parametrize('name', ['install.py', 'install_gui.py'])
def test_no_hard_coded_port(name):
    assert 'localhost:5000' not in _read(name)


def test_gui_lets_the_app_open_the_browser():
    src = _read('install_gui.py')
    assert "RETRODB_OPEN_BROWSER='1'" in src
    assert 'webbrowser' not in src


@pytest.mark.parametrize('name,venv', [
    ('start.sh', '.venv/bin/python'),
    ('start.command', '.venv/bin/python'),
    ('start.bat', '.venv\\Scripts\\python.exe'),
])
def test_launchers_use_retrodbs_own_python(name, venv):
    src = _read(name)
    # Once at start and once after the installer may have made the folder.
    assert src.count('pick_venv' if name != 'start.bat' else venv) >= 2
    assert venv in src
