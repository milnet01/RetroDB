# =============================================================================
# RETRODB - Get RetroArch: the player's program (PASS-59-139)
# =============================================================================
# Downloads the official RetroArch from libretro's build server into
# <profile>/app/, beside the player's settings. RetroDB links and downloads;
# it does not redistribute RetroArch (user, 2026-10-23).
#
#   program()     the installed program, or None
#   launch_env()  the environment the installed Linux program runs with
#   install()     download, check, unpack, move into place
#
# Every download is a fixed URL with a pinned SHA-256, so a changed file on
# either server installs nothing. libretro ships Linux and Windows as .7z;
# the Windows one uses the BCJ2 filter, which neither py7zr nor Windows' own
# tar reads, so 7-Zip's pinned stand-alone tool unpacks both. macOS ships a
# .dmg, which the system's hdiutil opens. The macOS path is unverified.
# =============================================================================

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Optional

import requests

import platform_utils
from services import player, player_cores

logger = logging.getLogger(__name__)

VERSION = '1.22.2'
_RA = f'https://buildbot.libretro.com/stable/{VERSION}'
_7Z = 'https://github.com/ip7z/7zip/releases/download/26.05'

# host: (RetroArch download, SHA-256)
DOWNLOADS = {
    'linux': (f'{_RA}/linux/x86_64/RetroArch.7z',
              '7d62da9a21397d6e1b9490785cedbeafd262781b50115076736fbe8a77ef30e9'),
    'windows': (f'{_RA}/windows/x86_64/RetroArch.7z',
                'b2139b1d0f9d4526dc6b5ce23cbb3efdc766096fa6f2c3df016818b486ac6372'),
    'macos': (f'{_RA}/apple/osx/universal/RetroArch_Metal.dmg',
              '81b79121ba26d539064ae13b4d0419a120c3d165afbe656cf5f5412b15fdb434'),
}
# host: (7-Zip's stand-alone tool, SHA-256 as its GitHub release lists it)
SEVEN_ZIP = {
    'linux': (f'{_7Z}/7z2605-linux-x64.tar.xz',
              '22cf82fcc6eb7474f1d5bb4f02c0f8ebd573a718089d6833dc30f8350a3b232e'),
    'windows': (f'{_7Z}/7zr.exe',
                '9bf582b894dfa665f852d7e9112b02290a1c303c2d95a21fcdc41ffcb03143b7'),
}
_LINUX_DIR = 'RetroArch-Linux-x86_64'
# host: the program, under <profile>/app/
PROGRAMS = {
    'linux': f'{_LINUX_DIR}/squashfs-root/AppRun',
    'windows': 'RetroArch-Win64/retroarch.exe',
    'macos': 'RetroArch.app/Contents/MacOS/RetroArch',
}
MAX_BYTES = 512 * 1024 * 1024
_CHUNK = 1024 * 1024
_RUN_TIMEOUT = 600


class InstallError(Exception):
    """An install that put nothing in place."""


def host() -> Optional[str]:
    """'linux', 'windows' or 'macos' where libretro builds RetroArch for this
    computer, else None. The Linux and Windows builds are x86_64 only; the
    macOS one is universal."""
    if platform_utils.IS_MACOS:
        return 'macos'
    if platform.machine().lower() not in ('x86_64', 'amd64'):
        return None
    if platform_utils.IS_WINDOWS:
        return 'windows'
    if platform_utils.IS_LINUX:
        return 'linux'
    return None


def app_dir() -> Path:
    return player.profile_dir() / 'app'


def program() -> Optional[Path]:
    """The installed RetroArch program, if it is there and runnable."""
    h = host()
    if h is None:
        return None
    path = app_dir() / PROGRAMS[h]
    return path if path.is_file() and os.access(path, os.X_OK) else None


def installed_version() -> Optional[str]:
    try:
        return json.loads((app_dir() / 'installed.json').read_text(encoding='utf-8'))['version']
    except (OSError, ValueError, KeyError, TypeError):
        return None


def launch_env(binary: str) -> Optional[dict]:
    """The installed Linux program runs with HOME set to the folder libretro
    ships beside its AppImage, as the AppImage itself does: its menus, core
    information and controller profiles are there. Any other program runs
    with RetroDB's own environment (None)."""
    installed = program()
    if host() != 'linux' or installed is None or Path(binary) != installed:
        return None
    env = {k: v for k, v in os.environ.items()
           if not k.startswith('XDG_') or k == 'XDG_RUNTIME_DIR'}
    env['HOME'] = str(app_dir() / _LINUX_DIR / f'{_LINUX_DIR}.AppImage.home')
    return env


# -----------------------------------------------------------------------------
# The two outside calls; tests replace both
# -----------------------------------------------------------------------------

def _http_get(url: str):
    # Redirects are followed: GitHub serves release files from another host.
    # The pinned SHA-256, not the host, decides what installs.
    return requests.get(url, stream=True, timeout=30)


def _run(argv: list, cwd: Optional[Path] = None) -> None:
    try:
        done = subprocess.run(argv, cwd=cwd, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                              timeout=_RUN_TIMEOUT, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise InstallError(f'{Path(argv[0]).name} failed: {e}') from e
    if done.returncode != 0:
        tail = done.stderr.decode('utf-8', 'replace').strip().splitlines()[-1:]
        raise InstallError(f'{Path(argv[0]).name} exited {done.returncode}'
                           + (f': {tail[0]}' if tail else ''))


def _download(url: str, sha256: str, dest: Path) -> None:
    r = _http_get(url)
    try:
        if r.status_code != 200:
            raise InstallError(f'HTTP {r.status_code} from {url}')
        digest, total, size = hashlib.sha256(), 0, player_cores.content_length(r)
        with open(dest, 'wb') as f:
            for chunk in r.iter_content(_CHUNK):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise InstallError('the download is larger than 512 MiB')
                digest.update(chunk)
                f.write(chunk)
                player_cores.report_progress(total, size)
    finally:
        r.close()
    if digest.hexdigest() != sha256:
        raise InstallError(f'{url} failed its checksum')


# -----------------------------------------------------------------------------
# Unpacking, per host, into an empty staging folder
# -----------------------------------------------------------------------------

def _seven_zip(h: str, work: Path) -> Path:
    url, sha = SEVEN_ZIP[h]
    if h == 'windows':
        tool = work / '7zr.exe'
        _download(url, sha, tool)
        return tool
    archive = work / '7z.tar.xz'
    _download(url, sha, archive)
    with tarfile.open(archive) as tf:
        tf.extractall(work / '7z', members=[tf.getmember('7zz')], filter='data')
    tool = work / '7z' / '7zz'
    tool.chmod(0o700)
    return tool


def _unpack(h: str, archive: Path, work: Path, staging: Path) -> None:
    if h == 'macos':
        mount = work / 'mnt'
        mount.mkdir()
        _run(['hdiutil', 'attach', '-nobrowse', '-readonly', '-noautoopen',
              '-mountpoint', str(mount), str(archive)])
        try:
            _run(['ditto', str(mount / 'RetroArch.app'), str(staging / 'RetroArch.app')])
        finally:
            _run(['hdiutil', 'detach', str(mount), '-force'])
        return
    _run([str(_seven_zip(h, work)), 'x', '-y', f'-o{staging}', str(archive)])
    if h == 'linux':
        # Unpacked once here, so the program runs without FUSE.
        folder = staging / _LINUX_DIR
        _run([str(folder / f'{_LINUX_DIR}.AppImage'), '--appimage-extract'], cwd=folder)


def install() -> Path:
    """Download and install RetroArch into <profile>/app/, whole or not at
    all: an existing install stays until the new one is complete. Returns
    the program. Raises InstallError."""
    h = host()
    if h is None:
        raise InstallError('libretro does not build RetroArch for this computer')
    url, sha = DOWNLOADS[h]
    profile = player.profile_dir()
    work = staging = None
    try:
        profile.mkdir(parents=True, exist_ok=True)
        work = Path(tempfile.mkdtemp(dir=profile, prefix='.app-work-'))
        staging = Path(tempfile.mkdtemp(dir=profile, prefix='.app-new-'))
        archive = work / url.rsplit('/', 1)[1]
        _download(url, sha, archive)
        _unpack(h, archive, work, staging)
        if not (staging / PROGRAMS[h]).is_file():
            raise InstallError(f'the download holds no {PROGRAMS[h]}')
        (staging / 'installed.json').write_text(
            json.dumps({'version': VERSION, 'sha256': sha}), encoding='utf-8')
        dest = app_dir()
        old = None
        if dest.exists():
            old = profile / f'.app-old-{os.getpid()}'
            os.replace(dest, old)
        os.replace(staging, dest)
        staging = None
        if old:
            shutil.rmtree(old, ignore_errors=True)
        logger.info("RetroArch %s installed in %s", VERSION, dest)
        return dest / PROGRAMS[h]
    except (OSError, tarfile.TarError, KeyError, requests.RequestException) as e:
        raise InstallError(str(e)) from e
    finally:
        for d in (work, staging):
            if d:
                shutil.rmtree(d, ignore_errors=True)
