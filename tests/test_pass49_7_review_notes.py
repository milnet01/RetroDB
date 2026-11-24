"""PASS-49-7 — small review notes: job status names and image-job overlap."""

import pytest

from services.jobs import base


@pytest.fixture
def lock_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(base, '_JOB_LOCK_DIR', str(tmp_path))
    return tmp_path


def test_museum_status_carries_the_toast_contract_names():
    from services.jobs.museum import MuseumGenerateJob
    job = MuseumGenerateJob()
    job.total_systems = 4
    job.current_index = 3
    job.success_count, job.failed_count, job.skipped_count = 1, 1, 0
    s = job.get_status()
    assert (s['current'], s['total'], s['percent']) == (3, 4, 50)
    assert (s['processed'], s['processing']) == (2, 3)
    assert (s['success'], s['failed'], s['skipped']) == (1, 1, 0)
    # The Museum page still reads the old names.
    assert (s['current_index'], s['total_systems'], s['success_count']) == (3, 4, 1)


def test_museum_status_with_no_systems_has_no_progress():
    from services.jobs.museum import MuseumGenerateJob
    s = MuseumGenerateJob().get_status()
    assert (s['total'], s['percent'], s['processing']) == (0, 0, 0)


def test_job_lock_held_sees_another_holder(lock_dir):
    assert base.job_lock_held('webp_migrate') is False
    fd = base.acquire_job_singleton_lock('webp_migrate')
    try:
        assert base.job_lock_held('webp_migrate') is True
    finally:
        base.release_job_singleton_lock(fd)
    assert base.job_lock_held('webp_migrate') is False


@pytest.mark.parametrize('starting,other', [
    ('image_resize', 'webp_migrate'),
    ('webp_migrate', 'image_resize'),
])
def test_an_image_job_waits_for_the_other(lock_dir, starting, other):
    """Both jobs rewrite the boxart folders, so one must not start while
    the other runs (it would strand an orphan .png)."""
    from services.jobs.image_resize import ImageResizeJob
    from services.jobs.webp_migrate import WebPMigrateJob
    job = ImageResizeJob() if starting == 'image_resize' else WebPMigrateJob()
    fd = base.acquire_job_singleton_lock(other)
    try:
        result = job.start()
    finally:
        base.release_job_singleton_lock(fd)
    assert result['success'] is False
    assert 'finish first' in result['error']
    assert job.running is False


@pytest.mark.parametrize('pinned_as,asked_as', [
    ('Example.COM', 'example.com'),
    ('example.com.', 'example.com'),
    ('example.com', 'EXAMPLE.com.'),
])
def test_a_pin_holds_whatever_case_or_trailing_dot(pinned_as, asked_as):
    import socket
    from services import ssrf
    with ssrf.pin_host_ip(pinned_as, '203.0.113.7'):
        answer = socket.getaddrinfo(asked_as, 443)
    assert answer[0][4][0] == '203.0.113.7'
