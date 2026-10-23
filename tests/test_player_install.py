# PASS-59-139 — Get RetroArch: the player's program, downloaded from libretro
# with a pinned SHA-256. No network and no real archive: the download and the
# unpack are stubbed, and the 7-Zip tool comes from a tar built here.
import hashlib
import io
import os
import tarfile

import pytest

from services import player_install


class _Response:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def iter_content(self, size):
        for i in range(0, len(self.body), size):
            yield self.body[i:i + size]

    def close(self):
        pass


@pytest.fixture
def linux(monkeypatch, tmp_path):
    """A Linux x86_64 host, the profile under tmp_path, and one download body
    whose SHA-256 every pin is set to."""
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path / 'base'))
    monkeypatch.setattr(player_install, 'host', lambda: 'linux')
    body = b'retroarch-archive'
    sha = hashlib.sha256(body).hexdigest()
    monkeypatch.setitem(player_install.DOWNLOADS, 'linux',
                        ('https://example.invalid/RetroArch.7z', sha))
    fetched = []

    def get(url):
        fetched.append(url)
        return _Response(body)
    monkeypatch.setattr(player_install, '_http_get', get)
    return {'body': body, 'sha': sha, 'fetched': fetched}


def _fake_unpack(h, archive, work, staging):
    prog = staging / player_install.PROGRAMS[h]
    prog.parent.mkdir(parents=True)
    prog.write_text('#!/bin/sh\n')
    prog.chmod(0o755)


def _leftovers():
    return sorted(p.name for p in player_install.player.profile_dir().glob('.app-*'))


def test_install_puts_the_program_in_place(linux, monkeypatch):
    monkeypatch.setattr(player_install, '_unpack', _fake_unpack)
    prog = player_install.install()
    assert prog == player_install.app_dir() / player_install.PROGRAMS['linux']
    assert player_install.program() == prog
    assert player_install.installed_version() == player_install.VERSION
    assert _leftovers() == []


def test_checksum_mismatch_installs_nothing(linux, monkeypatch):
    monkeypatch.setitem(player_install.DOWNLOADS, 'linux',
                        ('https://example.invalid/RetroArch.7z', '0' * 64))
    monkeypatch.setattr(player_install, '_unpack',
                        lambda *a: pytest.fail('a failed checksum must not unpack'))
    with pytest.raises(player_install.InstallError, match='checksum'):
        player_install.install()
    assert player_install.program() is None
    assert _leftovers() == []


def test_http_error_installs_nothing(linux, monkeypatch):
    monkeypatch.setattr(player_install, '_http_get', lambda url: _Response(b'', 404))
    with pytest.raises(player_install.InstallError, match='HTTP 404'):
        player_install.install()
    assert player_install.program() is None


def test_failed_unpack_keeps_the_existing_install(linux, monkeypatch):
    monkeypatch.setattr(player_install, '_unpack', _fake_unpack)
    first = player_install.install()

    def broken(h, archive, work, staging):
        raise player_install.InstallError('7zz exited 2')
    monkeypatch.setattr(player_install, '_unpack', broken)
    with pytest.raises(player_install.InstallError):
        player_install.install()
    assert player_install.program() == first
    assert _leftovers() == []


def test_download_without_the_program_is_refused(linux, monkeypatch):
    monkeypatch.setattr(player_install, '_unpack', lambda *a: None)
    with pytest.raises(player_install.InstallError, match='holds no'):
        player_install.install()
    assert player_install.program() is None


def test_linux_seven_zip_comes_from_its_pinned_tar(linux, monkeypatch, tmp_path):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w:xz') as tf:
        for name, data in (('7zz', b'#!/bin/sh\n'), ('readme.txt', b'x')):
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    body = buf.getvalue()
    monkeypatch.setitem(player_install.SEVEN_ZIP, 'linux',
                        ('https://example.invalid/7z.tar.xz', hashlib.sha256(body).hexdigest()))
    monkeypatch.setattr(player_install, '_http_get', lambda url: _Response(body))
    work = tmp_path / 'work'
    work.mkdir()
    tool = player_install._seven_zip('linux', work)
    assert tool == work / '7z' / '7zz' and os.access(tool, os.X_OK)
    assert not (work / '7z' / 'readme.txt').exists()


@pytest.mark.parametrize('platform_flags,machine,expected', [
    ((True, False, False), 'x86_64', 'linux'),
    ((True, False, False), 'aarch64', None),
    ((False, True, False), 'AMD64', 'windows'),
    ((False, False, True), 'arm64', 'macos'),
])
def test_host(monkeypatch, platform_flags, machine, expected):
    linux_, windows, macos = platform_flags
    monkeypatch.setattr('platform_utils.IS_LINUX', linux_)
    monkeypatch.setattr('platform_utils.IS_WINDOWS', windows)
    monkeypatch.setattr('platform_utils.IS_MACOS', macos)
    monkeypatch.setattr('services.player_install.platform.machine', lambda: machine)
    assert player_install.host() == expected


def test_launch_env_sets_home_for_the_installed_linux_program(linux, monkeypatch):
    monkeypatch.setattr(player_install, '_unpack', _fake_unpack)
    prog = player_install.install()
    monkeypatch.setenv('XDG_CONFIG_HOME', '/elsewhere')
    monkeypatch.setenv('XDG_RUNTIME_DIR', '/run/user/1000')
    env = player_install.launch_env(str(prog))
    assert env['HOME'].endswith('RetroArch-Linux-x86_64.AppImage.home')
    assert 'XDG_CONFIG_HOME' not in env and env['XDG_RUNTIME_DIR'] == '/run/user/1000'
    assert player_install.launch_env('/usr/bin/retroarch') is None


def test_player_row_resolves_to_the_installed_program(linux, monkeypatch):
    from services.launch_resolver import _resolve_binary
    row = {'binary_path_override': None, 'is_retroarch': 0, 'is_player': 1,
           'binary_name': 'retrodb-player-not-on-path'}
    monkeypatch.setattr(player_install, '_unpack', _fake_unpack)
    prog = player_install.install()
    assert _resolve_binary(row, None) == str(prog)


def test_override_still_wins_over_the_installed_program(linux, monkeypatch, tmp_path):
    from services.launch_resolver import _resolve_binary
    mine = tmp_path / 'my-retroarch'
    mine.write_text('#!/bin/sh\n')
    mine.chmod(0o755)
    monkeypatch.setattr(player_install, '_unpack', _fake_unpack)
    player_install.install()
    row = {'binary_path_override': str(mine), 'is_retroarch': 0, 'is_player': 1,
           'binary_name': 'retrodb-player'}
    assert _resolve_binary(row, None) == str(mine)


# -----------------------------------------------------------------------------
# The route behind Settings > Emulators > Get RetroArch
# -----------------------------------------------------------------------------

@pytest.fixture
def admin_client(monkeypatch):
    import app as mod
    from tests.test_routes_launch import _make_authed_client
    monkeypatch.setitem(mod.app.config, 'TESTING', True)
    return _make_authed_client(mod, monkeypatch, 'admin')


CSRF = {'X-CSRF-Token': 'test-csrf-token'}


def test_route_queues_retroarch_on_the_core_job(admin_client, monkeypatch):
    from services.jobs import player_cores_job
    from services.jobs.player_cores import RETROARCH
    calls = []
    monkeypatch.setattr(player_install, 'host', lambda: 'linux')
    monkeypatch.setattr(player_cores_job, 'request',
                        lambda items, force=False: calls.append((items, force)) or 'job-1')
    rv = admin_client.post('/api/player/retroarch/install', headers=CSRF)
    assert rv.status_code == 200 and rv.get_json()['job_id'] == 'job-1'
    assert calls == [([(RETROARCH, None)], True)]


def test_route_refuses_a_computer_libretro_does_not_build_for(admin_client, monkeypatch):
    monkeypatch.setattr(player_install, 'host', lambda: None)
    assert admin_client.post('/api/player/retroarch/install', headers=CSRF).status_code == 400


def test_route_needs_manage_settings(monkeypatch):
    import app as mod
    from tests.test_routes_launch import _make_authed_client
    monkeypatch.setitem(mod.app.config, 'TESTING', True)
    client = _make_authed_client(mod, monkeypatch, 'player')
    assert client.post('/api/player/retroarch/install', headers=CSRF).status_code == 403
