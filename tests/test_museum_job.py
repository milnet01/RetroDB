"""Tests for MuseumGenerateJob persistence + dedup singleton — Pass 19.5."""

import threading
from unittest.mock import patch

import pytest


class TestSingletonDedup:
    def test_only_one_singleton_in_package(self):
        """The duplicate `museum_generate_job` declaration in
        services/jobs/museum.py was deleted; the canonical singleton lives
        in services/jobs/__init__.py."""
        from services.jobs import museum_generate_job as pkg_singleton
        from services.jobs import museum as museum_mod

        assert not hasattr(museum_mod, 'museum_generate_job'), \
            "museum.py should no longer declare a singleton (duplicate state risk)"
        assert pkg_singleton is not None


class TestPersistenceContract:
    def test_class_exposes_resume_from_params(self):
        from services.jobs.museum import MuseumGenerateJob
        assert hasattr(MuseumGenerateJob, 'resume_from_params')
        assert callable(MuseumGenerateJob.resume_from_params)

    def test_get_status_takes_lock(self):
        """get_status() must take self._lock per the audit finding —
        otherwise a worker mid-update can serve a torn dict."""
        from services.jobs.museum import MuseumGenerateJob

        job = MuseumGenerateJob()

        # Replace the lock with a tracker so we can confirm acquisition
        original_lock = job._lock
        acquired = []

        class TrackingLock:
            def __enter__(self_inner):
                acquired.append(True)
                return original_lock.__enter__()
            def __exit__(self_inner, *a):
                return original_lock.__exit__(*a)

        job._lock = TrackingLock()
        job.get_status()
        assert acquired, "get_status() did not acquire self._lock"


class TestResumeFromParams:
    def test_resume_skips_already_processed_indices(self):
        """resume_from_params should accept a progress dict and skip past
        the indices already done (current=N -> start at N)."""
        from services.jobs.museum import MuseumGenerateJob

        job = MuseumGenerateJob()

        # Stub _worker so it just records the resume_index it sees.
        seen_resume_index = {}
        worker_finished = threading.Event()

        def fake_worker(self, system_ids=None):
            try:
                seen_resume_index['value'] = self._resume_index
                seen_resume_index['success'] = self.success_count
                seen_resume_index['failed'] = self.failed_count
                seen_resume_index['skipped'] = self.skipped_count
                seen_resume_index['overwrite'] = self.overwrite
            finally:
                with self._lock:
                    self.running = False
                    self.completed = True
                worker_finished.set()

        with patch.object(MuseumGenerateJob, '_worker', fake_worker):
            ok = job.resume_from_params(
                params={'system_ids': [1, 2, 3, 4, 5], 'overwrite': True},
                progress={'current': 3, 'success': 2, 'failed': 1, 'skipped': 0},
            )
            assert ok is True
            assert worker_finished.wait(timeout=2.0)

        assert seen_resume_index['value'] == 3
        assert seen_resume_index['success'] == 2
        assert seen_resume_index['failed'] == 1
        assert seen_resume_index['overwrite'] is True

    def test_resume_refuses_when_already_running(self):
        from services.jobs.museum import MuseumGenerateJob
        job = MuseumGenerateJob()
        job.running = True

        ok = job.resume_from_params(
            params={'system_ids': [1], 'overwrite': False},
            progress=None,
        )
        assert ok is False
