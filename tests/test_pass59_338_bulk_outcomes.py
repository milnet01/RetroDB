"""PASS-59-338: a bulk scrape keeps the games it failed or skipped, with why.

The list lives in bulk_scrape_outcomes, so a reload or a restart still shows
it; a fresh bulk scrape empties it, and the status reply carries its counts.
"""
import pytest

from services.jobs import bulk_scrape as bs


@pytest.fixture
def empty_list():
    import app  # noqa: F401 — builds the throwaway schema, migration 050 included
    bs.clear_outcomes()
    yield
    bs.clear_outcomes()


def test_outcomes_are_kept_in_order_with_reason_and_counted(empty_list):
    bs.record_outcome('job-a', 7, 'Alpha', 'failed', 'no_match')
    bs.record_outcome('job-a', 8, 'Beta', 'skipped', 'cooldown')
    bs.record_outcome('job-b', 9, None, 'failed', 'error', 'boom ' * 100)

    games = bs.list_outcomes()
    assert [(g['game_id'], g['title'], g['outcome'], g['reason']) for g in games] == [
        (7, 'Alpha', 'failed', 'no_match'),
        (8, 'Beta', 'skipped', 'cooldown'),
        (9, None, 'failed', 'error'),
    ]
    assert len(games[2]['detail']) == 300          # an error's text is clipped
    assert bs.outcome_summary() == {'job_id': 'job-a', 'failed': 2, 'skipped': 1}

    bs.clear_outcomes()
    assert bs.list_outcomes() == []
    assert bs.outcome_summary() == {'job_id': None, 'failed': 0, 'skipped': 0}


def test_every_recorded_reason_is_one_the_page_words(empty_list):
    # The browser has a sentence for each reason; a new reason needs one.
    import os
    from tests._util import REPO_ROOT
    js = open(os.path.join(REPO_ROOT, 'static', 'js', 'bulk-scrape-outcomes.js'), encoding='utf-8').read()
    for reason in bs.OUTCOME_REASONS:
        assert f"{reason}:" in js, reason


def test_status_and_outcomes_api(empty_list, admin_test_client):
    bs.record_outcome('job-c', 11, 'Gamma', 'failed', 'no_results')
    client, _csrf = admin_test_client()
    status = client.get('/api/bulk-scrape-job/status').get_json()
    assert status['outcomes'] == {'job_id': 'job-c', 'failed': 1, 'skipped': 0}
    reply = client.get('/api/bulk-scrape-job/outcomes').get_json()
    assert reply['games'] == [{'game_id': 11, 'title': 'Gamma', 'outcome': 'failed',
                               'reason': 'no_results', 'detail': None}]


def test_a_fresh_start_empties_the_list(empty_list, monkeypatch):
    bs.record_outcome('old', 1, 'Old', 'failed', 'no_match')
    job = bs.BulkScrapeJob()
    monkeypatch.setattr(bs, 'acquire_job_singleton_lock', lambda _name: 0)
    monkeypatch.setattr(bs, 'release_job_singleton_lock', lambda _fd: None)
    monkeypatch.setattr(bs.threading, 'Thread', _NoThread)
    job.start([1], None, '/games', 'fill_missing')
    assert bs.list_outcomes() == []


class _NoThread:
    def __init__(self, *a, **k):
        pass

    def start(self):
        pass
