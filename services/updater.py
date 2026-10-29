# =============================================================================
# RETRODB - Self-updater (PASS-59-169)
# =============================================================================
# Checks GitHub Releases for a newer RetroDB, downloads and verifies the
# release for this install, and hands over to the new version's helper
# (updater_apply.py), which swaps the files, restarts and rolls back on
# failure. Admin-only; installing always takes a click.
#
#   status()          what the Settings card and dashboard banner show
#   check(force)      query GitHub (cached for CHECK_INTERVAL)
#   job.start()       download + verify + unpack in the background
#   install()         back up the DB, write the plan, start the helper
#
# Contract: docs/specs/PASS-59-169-self-updater.md.
# =============================================================================

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import zipfile
from datetime import datetime, timezone
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)

RELEASES_REPO = 'milnet01/RetroDB'
LATEST_URL = f'https://api.github.com/repos/{RELEASES_REPO}/releases/latest'
DOWNLOAD_PREFIX = f'https://github.com/{RELEASES_REPO}/releases/download/'
CHECK_INTERVAL = 24 * 3600
MAX_DOWNLOAD = 3 * 1024 ** 3
MAX_UNPACKED = 8 * 1024 ** 3
MAX_CHECKSUM_FILE = 64 * 1024
_CHUNK = 1024 * 1024


class UpdateError(Exception):
    pass


# -----------------------------------------------------------------------------
# Paths
# -----------------------------------------------------------------------------

def _base():
    return config.BASE_DIR


def update_dir():
    return os.path.join(_base(), '.update')


def _paths():
    root = update_dir()
    return {
        'root': root,
        'download': os.path.join(root, 'download'),
        'staging': os.path.join(root, 'staging'),
        'plan': os.path.join(root, 'plan.json'),
        'check': os.path.join(_base(), 'data', 'update_check.json'),
        'status': os.path.join(_base(), 'data', 'update_status.json'),
        'log': os.path.join(_base(), 'logs', 'update.log'),
    }


# -----------------------------------------------------------------------------
# Versions, install kind, asset choice
# -----------------------------------------------------------------------------

def parse_version(text) -> Optional[tuple]:
    """'v3.33.0' / '3.33.0' -> (3, 33, 0); None when it is not X.Y.Z."""
    m = re.fullmatch(r'v?(\d+)\.(\d+)\.(\d+)', str(text or '').strip())
    return tuple(int(p) for p in m.groups()) if m else None


def is_newer(latest, current) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


def host_platform() -> Optional[str]:
    if sys.platform.startswith('linux'):
        return 'Linux'
    if sys.platform == 'darwin':
        return 'macOS'
    if sys.platform == 'win32':
        return 'Windows'
    return None


def install_kind() -> tuple:
    """(kind, reason): kind is 'source' / 'standalone', or None with the
    reason one-click install is not offered here."""
    if os.environ.get('LWSM_MANAGED') == '1':
        return None, 'managed'
    if getattr(sys, 'frozen', False):
        return 'standalone', None
    if os.path.exists(os.path.join(_base(), '.git')):
        return None, 'git'
    return 'source', None


def asset_names(version, kind, platform) -> list:
    """Release asset names for this install, most preferred first."""
    if kind == 'source':
        return [f'RetroDB-v{version}-{platform}.zip']
    return [f'RetroDB-v{version}-{platform}-Standalone.zip',
            f'RetroDB-v{version}-{platform}-CPU-Standalone.zip']


def pick_asset(release, kind, platform) -> Optional[dict]:
    """{'name', 'url', 'size', 'checksum_url'} for this install, or None."""
    if not kind or not platform:
        return None
    assets = {a.get('name'): a for a in release.get('assets') or [] if isinstance(a, dict)}
    # A GitHub release (`tag_name`) or this module's cached summary (`tag`).
    version = '.'.join(map(str, parse_version(release.get('tag_name') or release.get('tag')) or ()))
    for name in asset_names(version, kind, platform):
        asset = assets.get(name)
        if not asset:
            continue
        checksum = assets.get('SHA256SUMS.txt' if kind == 'source' else f'{name}.sha256')
        if not checksum:
            continue
        url, sum_url = asset.get('browser_download_url'), checksum.get('browser_download_url')
        if not (_allowed_url(url) and _allowed_url(sum_url)):
            continue
        return {'name': name, 'url': url, 'size': asset.get('size') or 0,
                'checksum_url': sum_url}
    return None


def _allowed_url(url) -> bool:
    return isinstance(url, str) and url.startswith(DOWNLOAD_PREFIX) and '..' not in url


def checksum_for(text, name) -> Optional[str]:
    """The SHA-256 a `sha256sum`-style file gives for `name`. A one-line
    file naming no file (a bare hash) counts for any name."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    for line in lines:
        parts = line.split()
        digest = parts[0].lower()
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            continue
        if len(parts) == 1 and len(lines) == 1:
            return digest
        if len(parts) >= 2 and os.path.basename(parts[-1].lstrip('*')) == name:
            return digest
    return None


# -----------------------------------------------------------------------------
# Checking
# -----------------------------------------------------------------------------

_check_lock = threading.Lock()
_check_cache = None   # {'checked_at': ts, 'release': {...} | None, 'error': str | None}


def _http_get(url, **kwargs):
    """The one network call; tests replace it."""
    headers = {'User-Agent': f'RetroDB/{config.APP_VERSION}',
               'Accept': 'application/vnd.github+json'}
    return requests.get(url, headers=headers, timeout=kwargs.pop('timeout', 15), **kwargs)


def _load_check():
    global _check_cache
    if _check_cache is None:
        try:
            with open(_paths()['check'], encoding='utf-8') as f:
                _check_cache = json.load(f)
        except (OSError, ValueError):
            _check_cache = {}
    return _check_cache


def _save_check(data):
    global _check_cache
    _check_cache = data
    try:
        from services.atomic_io import atomic_write_json
        atomic_write_json(_paths()['check'], data)
    except Exception as e:
        logger.debug(f"could not save update check: {e}")


def _summarise(release) -> dict:
    return {
        'version': '.'.join(map(str, parse_version(release.get('tag_name')))),
        'tag': release.get('tag_name'),
        'notes': (release.get('body') or '')[:20000],
        'url': release.get('html_url') if str(release.get('html_url') or '').startswith(
            f'https://github.com/{RELEASES_REPO}/') else None,
        'published_at': release.get('published_at'),
        'assets': [{'name': a.get('name'), 'browser_download_url': a.get('browser_download_url'),
                    'size': a.get('size')}
                   for a in release.get('assets') or [] if isinstance(a, dict)],
    }


def check(force=False) -> dict:
    """Ask GitHub for the latest release; cached for CHECK_INTERVAL."""
    with _check_lock:
        cached = _load_check()
        if not force and cached and time.time() - cached.get('checked_at', 0) < CHECK_INTERVAL:
            return cached
        data = {'checked_at': time.time(), 'release': None, 'error': None}
        try:
            r = _http_get(LATEST_URL)
            if r.status_code == 404:
                data['error'] = 'no published release'
            elif r.status_code != 200:
                data['error'] = f'GitHub answered {r.status_code}'
            else:
                release = r.json()
                if parse_version(release.get('tag_name')) and not release.get('draft') \
                        and not release.get('prerelease'):
                    data['release'] = _summarise(release)
                else:
                    data['error'] = 'latest release has no X.Y.Z tag'
        except (requests.RequestException, ValueError) as e:
            data['error'] = 'could not reach GitHub'
            logger.info(f"update check failed: {e}")
        _save_check(data)
        return data


def _background_check_if_due():
    try:
        import settings_manager
        if not settings_manager.get_setting('update_check_auto', True):
            return
    except Exception:
        pass
    cached = _load_check()
    if cached and time.time() - cached.get('checked_at', 0) < CHECK_INTERVAL:
        return
    if _check_lock.locked():
        return
    threading.Thread(target=check, name='update-check', daemon=True).start()


# -----------------------------------------------------------------------------
# Download, verify, unpack
# -----------------------------------------------------------------------------

def safe_extract(zip_path, dest) -> None:
    """Unpack `zip_path` into `dest`: no member may escape `dest`, symlinks
    are refused, Unix permission bits are kept. Raises UpdateError."""
    dest_real = os.path.realpath(dest)
    total = 0
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = info.filename
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UpdateError(f'the archive holds a link: {name}')
            if name.startswith(('/', '\\')) or re.match(r'^[A-Za-z]:', name):
                raise UpdateError(f'the archive holds an absolute path: {name}')
            target = os.path.realpath(os.path.join(dest_real, name))
            if target != dest_real and not target.startswith(dest_real + os.sep):
                raise UpdateError(f'the archive path leaves its folder: {name}')
            total += info.file_size
            if total > MAX_UNPACKED:
                raise UpdateError('the archive unpacks larger than 8 GiB')
        for info in zf.infolist():
            path = zf.extract(info, dest_real)
            mode = (info.external_attr >> 16) & 0o777
            if mode and not info.is_dir() and os.name != 'nt':
                os.chmod(path, (mode & 0o755) | stat.S_IRUSR | stat.S_IWUSR)


def _read_app_version(tree) -> Optional[str]:
    try:
        with open(os.path.join(tree, 'config.example.py'), encoding='utf-8') as f:
            m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', f.read(), re.M)
        return m.group(1) if m else None
    except OSError:
        return None


def program_name() -> str:
    return 'retrodb.exe' if sys.platform == 'win32' else 'retrodb'


def validate_tree(tree, kind, version) -> None:
    if kind == 'source':
        if not os.path.isfile(os.path.join(tree, 'app.py')) or \
                not os.path.isfile(os.path.join(tree, 'updater_apply.py')):
            raise UpdateError('the download is not a RetroDB source release')
        if _read_app_version(tree) != version:
            raise UpdateError('the download is not the expected version')
    else:
        if not os.path.isfile(os.path.join(tree, program_name())) or \
                not os.path.isdir(os.path.join(tree, '_internal')):
            raise UpdateError('the download is not a RetroDB standalone release')


class UpdateJob:
    """Download, verify and unpack one release. One at a time."""

    def __init__(self):
        self._lock = threading.Lock()
        self.reset()

    def reset(self):
        self.state = 'idle'        # idle | downloading | ready | installing | error
        self.version = None
        self.kind = None
        self.asset = None
        self.done_bytes = 0
        self.total_bytes = 0
        self.error = None
        self.tree = None

    def snapshot(self) -> dict:
        with self._lock:
            return {'state': self.state, 'version': self.version,
                    'done_bytes': self.done_bytes, 'total_bytes': self.total_bytes,
                    'error': self.error}

    def start(self, release) -> dict:
        kind, reason = install_kind()
        asset = pick_asset(release, kind, host_platform()) if kind else None
        if not asset:
            return {'success': False, 'error': reason or 'no_asset'}
        with self._lock:
            if self.state in ('downloading', 'installing'):
                return {'success': False, 'error': 'busy'}
            self.reset()
            self.state, self.version, self.kind = 'downloading', release['version'], kind
            self.asset, self.total_bytes = asset, asset['size']
        threading.Thread(target=self._run, name='update-download', daemon=True).start()
        return {'success': True}

    def _run(self):
        p = _paths()
        try:
            for d in (p['download'], p['staging']):
                shutil.rmtree(d, ignore_errors=True)
                os.makedirs(d, exist_ok=True)
            sums = self._fetch_checksums()
            expected = checksum_for(sums, self.asset['name'])
            if not expected:
                raise UpdateError('the release lists no checksum for this download')
            archive = os.path.join(p['download'], self.asset['name'])
            if self._download(archive) != expected:
                os.remove(archive)
                raise UpdateError('the download failed its checksum')
            safe_extract(archive, p['staging'])
            tops = [n for n in os.listdir(p['staging']) if not n.startswith('.')]
            if len(tops) != 1:
                raise UpdateError('the download is not a RetroDB release')
            tree = os.path.join(p['staging'], tops[0])
            validate_tree(tree, self.kind, self.version)
            with self._lock:
                self.tree, self.state = tree, 'ready'
            logger.info(f"update {self.version} downloaded and verified")
        except (UpdateError, OSError, zipfile.BadZipFile, requests.RequestException) as e:
            logger.warning(f"update download failed: {e}")
            with self._lock:
                self.state, self.error = 'error', str(e)

    def _fetch_checksums(self) -> str:
        r = _http_get(self.asset['checksum_url'], stream=True)
        try:
            if r.status_code != 200:
                raise UpdateError(f'HTTP {r.status_code} for the checksum file')
            body = b''
            for chunk in r.iter_content(8192):
                body += chunk
                if len(body) > MAX_CHECKSUM_FILE:
                    raise UpdateError('the checksum file is too large')
            return body.decode('utf-8', 'replace')
        finally:
            r.close()

    def _download(self, dest) -> str:
        r = _http_get(self.asset['url'], stream=True, timeout=60)
        digest = hashlib.sha256()
        try:
            if r.status_code != 200:
                raise UpdateError(f'HTTP {r.status_code} for the download')
            with open(dest, 'wb') as f:
                for chunk in r.iter_content(_CHUNK):
                    with self._lock:
                        self.done_bytes += len(chunk)
                        if self.done_bytes > MAX_DOWNLOAD:
                            raise UpdateError('the download is larger than 3 GiB')
                    digest.update(chunk)
                    f.write(chunk)
        finally:
            r.close()
        return digest.hexdigest()


job = UpdateJob()


# -----------------------------------------------------------------------------
# Install: hand over to the new version's helper
# -----------------------------------------------------------------------------

def _restart_argv() -> tuple:
    if getattr(sys, 'frozen', False):
        return [sys.executable] + sys.argv[1:], os.path.dirname(sys.executable)
    return [sys.executable] + sys.argv, os.getcwd()


def _install_dir(kind) -> str:
    return os.path.dirname(sys.executable) if kind == 'standalone' else _base()


def build_plan(tree, kind, version, port, db_backup) -> dict:
    p = _paths()
    argv, cwd = _restart_argv()
    return {
        'plan_version': 1, 'kind': kind,
        'from_version': config.APP_VERSION, 'to_version': version,
        'install_dir': _install_dir(kind),
        'staging_root': p['staging'], 'staging_dir': tree,
        'download_dir': p['download'],
        'rollback_dir': os.path.join(p['root'], f'rollback-{config.APP_VERSION}'),
        'pid': os.getpid(), 'port': port,
        'restart_argv': argv, 'restart_cwd': cwd,
        'db_path': config.DB_PATH, 'db_backup': db_backup,
        'status_path': p['status'], 'log_path': p['log'],
    }


def helper_argv(tree, kind, plan_path) -> list:
    if kind == 'standalone':
        return [os.path.join(tree, program_name()), '--apply-update', plan_path]
    return [sys.executable, os.path.join(tree, 'updater_apply.py'), plan_path]


def _backup_database(version) -> str:
    from services.database import backup_database
    backup_dir = os.path.join(os.path.dirname(config.DB_PATH), 'backups')
    os.makedirs(backup_dir, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    path = os.path.join(backup_dir, f'pre_update_{config.APP_VERSION}_to_{version}_{stamp}.db')
    backup_database(config.DB_PATH, path)
    return path


def _spawn(argv, cwd):
    import updater_apply
    return updater_apply.spawn_detached(argv, cwd, _paths()['log'])


def _shutdown_soon():
    """As /api/shutdown: let the reply flush, drain jobs, SIGTERM."""
    import signal

    def go():
        time.sleep(1)
        os.kill(os.getpid(), signal.SIGTERM)
    threading.Thread(target=go, daemon=True).start()


def install(port) -> dict:
    """Start the update that `job` has ready. Returns a result dict."""
    with job._lock:
        if job.state != 'ready':
            return {'success': False, 'error': 'not_ready'}
        job.state = 'installing'
        tree, kind, version = job.tree, job.kind, job.version
    try:
        db_backup = _backup_database(version)
        plan = build_plan(tree, kind, version, port, db_backup)
        plan_path = _paths()['plan']
        with open(plan_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f)
        try:
            os.remove(_paths()['status'])
        except OSError:
            pass
        _spawn(helper_argv(tree, kind, plan_path), tree)
    except Exception as e:
        logger.error(f"update install could not start: {e}", exc_info=True)
        with job._lock:
            job.state, job.error = 'error', str(e)
        return {'success': False, 'error': 'start_failed'}
    logger.info(f"updating to {version}: helper started, shutting down")
    _shutdown_soon()
    return {'success': True}


# -----------------------------------------------------------------------------
# Status
# -----------------------------------------------------------------------------

def last_result() -> Optional[dict]:
    """The helper's outcome file, after cleaning what the helper could not."""
    try:
        with open(_paths()['status'], encoding='utf-8') as f:
            result = json.load(f)
    except (OSError, ValueError):
        return None
    helper = result.get('helper_pid')
    if helper and helper != os.getpid():
        import updater_apply
        if not updater_apply.pid_alive(helper):
            shutil.rmtree(_paths()['staging'], ignore_errors=True)
            shutil.rmtree(_paths()['download'], ignore_errors=True)
    return result


def dismiss_result() -> None:
    try:
        os.remove(_paths()['status'])
    except OSError:
        pass


def status() -> dict:
    _background_check_if_due()
    cached = _load_check() or {}
    release = cached.get('release')
    kind, reason = install_kind()
    available = bool(release and is_newer(release.get('version'), config.APP_VERSION))
    can_install = False
    if available and kind:
        can_install = pick_asset(release, kind, host_platform()) is not None
        if not can_install:
            reason = 'no_asset'
    return {
        'current': config.APP_VERSION,
        'latest': {k: release.get(k) for k in ('version', 'notes', 'url', 'published_at')}
        if release else None,
        'available': available,
        'can_install': can_install,
        'reason': None if can_install else (reason if available else None),
        'checked_at': cached.get('checked_at'),
        'check_error': cached.get('error'),
        'job': job.snapshot(),
        'last_result': last_result(),
    }
