"""Tests for routes.settings._prune_old_backups — backup retention sweep
introduced in Pass 19.3."""

import os
import tempfile
import time

from routes.settings import _prune_old_backups


def _touch(path, mtime):
    with open(path, 'w') as f:
        f.write('x')
    os.utime(path, (mtime, mtime))


class TestPruneOldBackups:
    def test_keeps_newest_n_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            now = time.time()
            for i in range(10):
                _touch(os.path.join(tmp, f"roms_backup_{i:02d}.db"), now - (10 - i))

            _prune_old_backups(tmp, keep=3)

            remaining = sorted(f for f in os.listdir(tmp) if f.endswith('.db'))
            assert remaining == [
                'roms_backup_07.db',
                'roms_backup_08.db',
                'roms_backup_09.db',
            ]

    def test_pre_restore_backups_are_never_pruned(self):
        """Even when there are 50 pre_restore_* files, none should be deleted —
        users rely on them for recovery and they're created intentionally per
        restore."""
        with tempfile.TemporaryDirectory() as tmp:
            now = time.time()
            for i in range(20):
                _touch(os.path.join(tmp, f"roms_backup_{i:02d}.db"), now - (20 - i))
            for i in range(5):
                _touch(os.path.join(tmp, f"pre_restore_{i:02d}.db"), now - (5 - i))

            _prune_old_backups(tmp, keep=3)

            pre = sorted(f for f in os.listdir(tmp) if f.startswith('pre_restore_'))
            assert len(pre) == 5

    def test_keep_zero_is_noop(self):
        """`keep=0` (or negative) should not delete anything — defensive
        guard against a misconfigured MAX_BACKUPS wiping all backups."""
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                _touch(os.path.join(tmp, f"roms_backup_{i:02d}.db"), time.time() - i)

            _prune_old_backups(tmp, keep=0)

            assert len(os.listdir(tmp)) == 3

    def test_fewer_than_keep_is_noop(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                _touch(os.path.join(tmp, f"roms_backup_{i:02d}.db"), time.time() - i)

            _prune_old_backups(tmp, keep=10)

            assert len(os.listdir(tmp)) == 3

    def test_unrelated_files_are_ignored(self):
        """Files not matching the `roms_backup_*.db` pattern (e.g. README,
        .keep) should never be touched."""
        with tempfile.TemporaryDirectory() as tmp:
            now = time.time()
            for i in range(5):
                _touch(os.path.join(tmp, f"roms_backup_{i:02d}.db"), now - (5 - i))
            _touch(os.path.join(tmp, 'README.md'), now - 100)
            _touch(os.path.join(tmp, '.keep'), now - 100)

            _prune_old_backups(tmp, keep=2)

            files = sorted(os.listdir(tmp))
            assert 'README.md' in files
            assert '.keep' in files
            assert sum(1 for f in files if f.startswith('roms_backup_')) == 2
