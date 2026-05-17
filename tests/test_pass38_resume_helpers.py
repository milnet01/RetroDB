# =============================================================================
# Pass 38.8 — resume-path helpers
# =============================================================================
# Six job classes share the same resume_from_params scaffolding: pad the ID
# list with None placeholders, restore counts from progress, acquire the
# singleton lock or warn-and-bail. Pass 38.8 extracted three helpers in
# `services/jobs/base` so the duplication lives in one place. These tests pin
# the helpers' contracts and confirm every job class is calling them.
# =============================================================================

import os
import types

import pytest

from tests._util import REPO_ROOT as _REPO_ROOT


class TestPadResumeGameIds:
    """`pad_resume_game_ids` prepends None placeholders so the worker
    thread's `current_index` stays aligned with the original total."""

    def test_zero_resume_returns_unchanged_list(self):
        from services.jobs.base import pad_resume_game_ids

        result = pad_resume_game_ids(0, [10, 20, 30])
        assert result == [10, 20, 30]

    def test_resume_index_prepends_none_placeholders(self):
        from services.jobs.base import pad_resume_game_ids

        result = pad_resume_game_ids(3, [40, 50])
        assert result == [None, None, None, 40, 50]
        assert len(result) == 5

    def test_returns_a_new_list_not_an_alias(self):
        """Caller may mutate `remaining_ids` after calling — must not bleed
        back into the padded list."""
        from services.jobs.base import pad_resume_game_ids

        remaining = [1, 2, 3]
        result = pad_resume_game_ids(2, remaining)
        remaining.append(99)
        assert result == [None, None, 1, 2, 3]


class TestRestoreProgressCounts:
    """`restore_progress_counts` writes `current_index` + success / failed /
    skipped counts onto the job under the caller's lock."""

    def _make_job(self):
        job = types.SimpleNamespace(
            current_index=0,
            success_count=0,
            failed_count=0,
            skipped_count=0,
        )
        return job

    def test_restores_all_four_fields_from_progress_dict(self):
        from services.jobs.base import restore_progress_counts

        job = self._make_job()
        progress = {'success': 12, 'failed': 3, 'skipped': 1}
        restore_progress_counts(job, resume_index=16, progress=progress)
        assert job.current_index == 16
        assert job.success_count == 12
        assert job.failed_count == 3
        assert job.skipped_count == 1

    def test_progress_none_zeros_counts_but_keeps_resume_index(self):
        """A None progress dict (fresh resume from a snapshot without
        partial counts) must zero the counts, not crash."""
        from services.jobs.base import restore_progress_counts

        job = self._make_job()
        job.success_count = 99  # stale value should be overwritten
        restore_progress_counts(job, resume_index=5, progress=None)
        assert job.current_index == 5
        assert job.success_count == 0
        assert job.failed_count == 0
        assert job.skipped_count == 0

    def test_missing_keys_default_to_zero(self):
        """Older progress snapshots may lack one or more counter keys —
        helper must `.get(..., 0)` not `[...]`-fail."""
        from services.jobs.base import restore_progress_counts

        job = self._make_job()
        restore_progress_counts(job, resume_index=2, progress={'success': 7})
        assert job.success_count == 7
        assert job.failed_count == 0
        assert job.skipped_count == 0


class TestTryAcquireSingletonOrWarn:
    """`try_acquire_singleton_or_warn` consolidates the
    "acquire-or-log-and-bail" pattern across five resume paths."""

    def test_returns_fd_when_lock_acquired(self, monkeypatch):
        from services.jobs import base

        sentinel_fd = object()
        monkeypatch.setattr(
            base, 'acquire_job_singleton_lock', lambda name: sentinel_fd
        )
        result = base.try_acquire_singleton_or_warn('test_job')
        assert result is sentinel_fd

    def test_returns_none_and_logs_when_lock_held(self, monkeypatch, caplog):
        from services.jobs import base

        monkeypatch.setattr(
            base, 'acquire_job_singleton_lock', lambda name: None
        )
        with caplog.at_level('WARNING', logger='services.jobs.base'):
            result = base.try_acquire_singleton_or_warn('test_job')
        assert result is None
        assert 'test_job resume refused' in caplog.text
        assert 'lock held by another worker process' in caplog.text

    def test_kind_kwarg_customises_warning_text(self, monkeypatch, caplog):
        from services.jobs import base

        monkeypatch.setattr(
            base, 'acquire_job_singleton_lock', lambda name: None
        )
        with caplog.at_level('WARNING', logger='services.jobs.base'):
            base.try_acquire_singleton_or_warn('test_job', kind='start')
        assert 'test_job start refused' in caplog.text


class TestCallsitesUseHelpers:
    """Source-grep regression: every refactored job module imports the
    helpers (so a future revert to inline `[None] * resume_index + ...`
    won't go unnoticed)."""

    JOB_MODULES = (
        'services/jobs/ra_sync.py',
        'services/jobs/ra_refresh.py',
        'services/jobs/platform_sync.py',
        'services/jobs/psn_refresh.py',
        'services/jobs/bulk_scrape.py',
    )

    # bulk_scrape uses a queue-based promote/demote mechanism instead of
    # the cross-process singleton lock, so it's excluded from the
    # try_acquire_singleton_or_warn assertion. Derive the list from
    # JOB_MODULES so the two parametrize decorators can't drift
    # (test-audit VERB-2).
    SINGLETON_MODULES = tuple(m for m in JOB_MODULES if 'bulk_scrape' not in m)

    @pytest.mark.parametrize('rel_path', JOB_MODULES)
    def test_module_imports_pad_and_restore(self, rel_path):
        path = os.path.join(_REPO_ROOT, rel_path)
        with open(path, encoding='utf-8') as f:
            src = f.read()
        assert 'pad_resume_game_ids' in src, (
            f"{rel_path} must import + call pad_resume_game_ids "
            f"(Pass 38.8) — inline `[None] * resume_index + …` regressed."
        )
        assert 'restore_progress_counts' in src, (
            f"{rel_path} must import + call restore_progress_counts "
            f"(Pass 38.8)."
        )

    @pytest.mark.parametrize('rel_path', SINGLETON_MODULES)
    def test_singleton_module_uses_try_acquire_helper(self, rel_path):
        """Bulk scrape resume doesn't take the cross-process lock (it has
        a queue-based promote/demote mechanism instead), so it's excluded
        from this assertion. The four locked jobs must use the helper."""
        path = os.path.join(_REPO_ROOT, rel_path)
        with open(path, encoding='utf-8') as f:
            src = f.read()
        assert 'try_acquire_singleton_or_warn' in src, (
            f"{rel_path} resume path must use try_acquire_singleton_or_warn "
            f"(Pass 38.8) so the warning string stays consistent."
        )
