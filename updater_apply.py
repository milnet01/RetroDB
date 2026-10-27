# =============================================================================
# RETRODB - Update helper (PASS-59-169)
# =============================================================================
# Run by the OLD RetroDB, from the NEW version's unpacked tree, once the old
# one has been told to stop:
#
#   source:     python <staging>/updater_apply.py <plan.json>
#   standalone: <staging>/retrodb[.exe] --apply-update <plan.json>
#               (app.py hands the flag here before importing anything else)
#
# Waits for the old process to exit, swaps the program files, installs
# changed dependencies (source), starts RetroDB and waits for /health to
# report the new version. Anything that fails puts every file and the
# database back and starts the old version. Standard library only: the
# standalone runs this inside its own bundle, before Flask is imported.
# Contract: docs/specs/PASS-59-169-self-updater.md §5.
# =============================================================================

import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone

PLAN_VERSION = 1
EXIT_WAIT = 120
HEALTH_WAIT = 180

# Never written from the archive, whatever it holds (spec §5.2). config.py
# is replaced, but only from the new config.example.py (swap_source).
PROTECTED = frozenset({
    'config.py',
    'data/settings.json', 'data/scraper_settings.json',
    'data/rom_tools_config.json', 'data/psn_tokens.json',
    'data/xbox_tokens.json', 'data/.secret_key',
    'data/update_status.json', 'data/update_check.json',
})
PROTECTED_DIRS = ('database/', 'logs/', '.update/')

MANIFEST = os.path.join('.update', 'manifest.json')


def is_protected(rel):
    """True for a path (relative, '/'-separated) an update must not write."""
    rel = rel.replace(os.sep, '/')
    return rel in PROTECTED or rel.startswith(PROTECTED_DIRS)


class UpdateFailed(Exception):
    pass


class Log:
    def __init__(self, path):
        self.path = path

    def __call__(self, msg):
        line = f"{datetime.now(timezone.utc).isoformat(timespec='seconds')} updater: {msg}\n"
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, 'a', encoding='utf-8') as f:
                f.write(line)
        except OSError:
            pass


# -----------------------------------------------------------------------------
# Processes
# -----------------------------------------------------------------------------

def pid_alive(pid):
    if sys.platform == 'win32':
        import ctypes
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def wait_for_exit(pid, timeout=None):
    deadline = time.monotonic() + (EXIT_WAIT if timeout is None else timeout)
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.5)
    return False


def spawn_detached(argv, cwd, log_path, env=None):
    """Start `argv` so it outlives this helper; output goes to `log_path`."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    out = open(log_path, 'ab')
    kwargs = {'cwd': cwd, 'stdin': subprocess.DEVNULL, 'stdout': out,
              'stderr': subprocess.STDOUT, 'env': env, 'close_fds': True}
    if sys.platform == 'win32':
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | NEW_PROCESS_GROUP
        try:
            return subprocess.Popen(argv, creationflags=flags | 0x01000000, **kwargs)  # + BREAKAWAY_FROM_JOB
        except OSError:
            return subprocess.Popen(argv, creationflags=flags, **kwargs)
    return subprocess.Popen(argv, start_new_session=True, **kwargs)


def healthy_version(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=3) as r:
            if r.status != 200:
                return None
            return json.loads(r.read().decode('utf-8')).get('version')
    except Exception:
        return None


def wait_healthy(port, version, proc, timeout=None):
    deadline = time.monotonic() + (HEALTH_WAIT if timeout is None else timeout)
    while time.monotonic() < deadline:
        if healthy_version(port) == version:
            return True
        if proc is not None and proc.poll() is not None:
            return False  # exited before it came up
        time.sleep(1)
    return False


def stop(proc):
    if proc is None or proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(15)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(15)


# -----------------------------------------------------------------------------
# File swap with an undo record
# -----------------------------------------------------------------------------

class Swap:
    """Replace files under `install_dir`, keeping what it needs to undo."""

    def __init__(self, install_dir, rollback_dir, log):
        self.install_dir = install_dir
        self.rollback_dir = rollback_dir
        self.log = log
        self.moved = []   # rel paths whose old version sits in rollback_dir
        self.added = []   # rel paths that did not exist before

    def _set_aside(self, rel):
        src = os.path.join(self.install_dir, rel)
        if not os.path.lexists(src):
            return False
        dst = os.path.join(self.rollback_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        os.replace(src, dst)
        self.moved.append(rel)
        return True

    def put(self, rel, new_path):
        """Install `new_path` (file or directory) at `rel`."""
        existed = self._set_aside(rel)
        dst = os.path.join(self.install_dir, rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        # shutil.copy, not copy2: a copied file must look newer than any
        # compiled .pyc beside it. Python checks a .pyc by the source's size
        # and whole-second mtime, so carrying over the staged mtime let
        # config.py ("3.33.0" -> "3.33.1", same size) load its stale .pyc.
        if os.path.isdir(new_path):
            shutil.copytree(new_path, dst, symlinks=False, copy_function=shutil.copy)
        else:
            shutil.copy(new_path, dst)
        if not existed:
            self.added.append(rel)

    def remove(self, rel):
        self._set_aside(rel)

    def undo(self):
        for rel in reversed(self.added):
            path = os.path.join(self.install_dir, rel)
            try:
                if os.path.isdir(path) and not os.path.islink(path):
                    shutil.rmtree(path)
                elif os.path.lexists(path):
                    os.remove(path)
            except OSError as e:
                self.log(f'undo: could not remove {rel}: {e}')
        for rel in reversed(self.moved):
            dst = os.path.join(self.install_dir, rel)
            try:
                if os.path.isdir(dst) and not os.path.islink(dst):
                    shutil.rmtree(dst)
                elif os.path.lexists(dst):
                    os.remove(dst)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                os.replace(os.path.join(self.rollback_dir, rel), dst)
            except OSError as e:
                self.log(f'undo: could not restore {rel}: {e}')


def purge_bytecode(root):
    """Remove every __pycache__ under `root` (source installs), so neither
    the new files nor files a rollback put back can run stale bytecode."""
    for dirpath, dirnames, _files in os.walk(root):
        if '__pycache__' in dirnames:
            shutil.rmtree(os.path.join(dirpath, '__pycache__'), ignore_errors=True)
            dirnames.remove('__pycache__')
        dirnames[:] = [d for d in dirnames if d not in ('.update', 'database', 'logs', 'static')]


def tree_files(root):
    """Relative '/'-separated paths of every file under `root`."""
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for name in filenames:
            rel = os.path.relpath(os.path.join(dirpath, name), root)
            out.append(rel.replace(os.sep, '/'))
    return sorted(out)


def read_manifest(install_dir):
    try:
        with open(os.path.join(install_dir, MANIFEST), encoding='utf-8') as f:
            files = json.load(f).get('files', [])
        return [p for p in files if isinstance(p, str)]
    except (OSError, ValueError, AttributeError):
        return []


def write_manifest(install_dir, files, version):
    path = os.path.join(install_dir, MANIFEST)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'version': version, 'files': files}, f)


def swap_source(plan, swap):
    staging = plan['staging_dir']
    new_files = [p for p in tree_files(staging) if not is_protected(p)]
    new_set = set(new_files)
    for rel in new_files:
        swap.put(rel, os.path.join(staging, rel))
    # config.py is the installer's copy of config.example.py: app constants
    # only, APP_VERSION among them (user settings live in data/*.json). It
    # follows the new example deliberately; the old one stays in rollback_dir.
    example = os.path.join(staging, 'config.example.py')
    if os.path.isfile(example):
        swap.put('config.py', example)
    # Files the previous update installed that this version dropped.
    for rel in read_manifest(plan['install_dir']):
        if rel not in new_set and not is_protected(rel) and '..' not in rel.split('/'):
            swap.remove(rel)
    return new_files


def swap_standalone(plan, swap):
    staging = plan['staging_dir']
    for name in sorted(os.listdir(staging)):
        if is_protected(name) or name in ('database', 'logs', 'data', 'static'):
            continue
        swap.put(name, os.path.join(staging, name))


def file_digest(path):
    import hashlib
    try:
        with open(path, 'rb') as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def install_dependencies(plan, log):
    """Source installs: run the new tree's hash-locked pip install when the
    lockfile changed. Raises UpdateFailed."""
    install_dir = plan['install_dir']
    new_lock = os.path.join(install_dir, 'requirements.lock')
    old_lock = os.path.join(plan['rollback_dir'], 'requirements.lock')
    if file_digest(new_lock) == file_digest(old_lock):
        return
    sys.path.insert(0, install_dir)
    try:
        import installer_core
        args, source = installer_core.select_pip_args(install_dir)
        if args is None:
            return
        log(f'installing dependencies from {source}')
        result = installer_core.pip_install(args, install_dir, quiet=True)
    finally:
        sys.path.remove(install_dir)
    if result.returncode != 0:
        tail = (result.stderr or '').strip().splitlines()[-3:]
        raise UpdateFailed('dependency install failed: ' + ' | '.join(tail))


def restore_database(plan, log):
    backup, db = plan.get('db_backup'), plan.get('db_path')
    if not backup or not db or not os.path.exists(backup):
        return
    for suffix in ('-wal', '-shm'):
        try:
            os.remove(db + suffix)
        except OSError:
            pass
    shutil.copy2(backup, db)
    log(f'database restored from {os.path.basename(backup)}')


def write_status(plan, result, **extra):
    data = {'result': result, 'from_version': plan.get('from_version'),
            'to_version': plan.get('to_version'),
            'finished_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
            'helper_pid': os.getpid(), **extra}
    path = plan['status_path']
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f)
    os.replace(tmp, path)


def start_app(plan):
    env = dict(os.environ)
    env['RETRODB_OPEN_BROWSER'] = '0'
    env.pop('WERKZEUG_RUN_MAIN', None)
    return spawn_detached(plan['restart_argv'], plan['restart_cwd'], plan['log_path'], env)


def cleanup_after_success(plan):
    shutil.rmtree(plan['download_dir'], ignore_errors=True)
    if sys.platform != 'win32':
        # Windows cannot delete the tree this helper runs from; the app
        # removes it once this process is gone (spec §5.2, last paragraph).
        shutil.rmtree(plan['staging_root'], ignore_errors=True)


# -----------------------------------------------------------------------------
# Entry point
# -----------------------------------------------------------------------------

def apply(plan):
    log = Log(plan['log_path'])
    if plan.get('plan_version') != PLAN_VERSION:
        log(f"unknown plan version {plan.get('plan_version')}")
        return 2
    log(f"updating {plan['from_version']} -> {plan['to_version']} ({plan['kind']})")

    if not wait_for_exit(plan['pid']):
        log('the running RetroDB did not stop; nothing changed')
        write_status(plan, 'failed', reason='RetroDB did not stop')
        return 1

    shutil.rmtree(plan['rollback_dir'], ignore_errors=True)
    os.makedirs(plan['rollback_dir'], exist_ok=True)
    swap = Swap(plan['install_dir'], plan['rollback_dir'], log)
    proc = None
    new_files = None
    try:
        if plan['kind'] == 'standalone':
            swap_standalone(plan, swap)
        else:
            new_files = swap_source(plan, swap)
            purge_bytecode(plan['install_dir'])
            install_dependencies(plan, log)
        log('files swapped; starting the new version')
        proc = start_app(plan)
        if not wait_healthy(plan['port'], plan['to_version'], proc):
            raise UpdateFailed('the new version did not start')
    except Exception as e:
        reason = str(e) or type(e).__name__
        log(f'rolling back: {reason}')
        stop(proc)
        swap.undo()
        if plan['kind'] != 'standalone':
            purge_bytecode(plan['install_dir'])
        try:
            restore_database(plan, log)
        except OSError as db_err:
            log(f'database restore failed: {db_err}')
        try:
            old = start_app(plan)
            ok = wait_healthy(plan['port'], plan['from_version'], old)
            log('old version is running again' if ok else 'old version did not answer /health')
        except OSError as start_err:
            log(f'could not restart the old version: {start_err}')
        write_status(plan, 'rolled_back', reason=reason)
        return 1

    if new_files is not None:
        # Only now: a rolled-back update must leave the old list in place.
        write_manifest(plan['install_dir'], new_files, plan['to_version'])
    log('update finished')
    write_status(plan, 'updated')
    cleanup_after_success(plan)
    return 0


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == '--apply-update':
        argv = argv[1:]
    if len(argv) != 1:
        print('usage: updater_apply.py <plan.json>', file=sys.stderr)
        return 2
    with open(argv[0], encoding='utf-8') as f:
        plan = json.load(f)
    return apply(plan)


if __name__ == '__main__':
    sys.exit(main())
