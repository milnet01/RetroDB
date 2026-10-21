"""PASS-59-129: one log line per game says where its scrape time went.

The timer rides the progress marks the apply already makes
(services/apply_progress.py). Each second counts once, in the innermost step
running on the game's own thread, and it runs whether or not the game page's
progress tracker is active, so bulk scrapes log it too.
"""
import contextvars
import logging
import threading

import pytest

from services import apply_progress


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(apply_progress.time, 'monotonic', lambda: now[0])

    def at(t):
        now[0] = t
    return at


def _timing_lines(caplog):
    return [r.getMessage() for r in caplog.records if 'Scrape timing' in r.getMessage()]


def test_each_second_counts_once_in_the_innermost_step(clock, caplog):
    caplog.set_level(logging.INFO, logger='services.apply_progress')
    clock(0)
    assert apply_progress.timing_start('Lufia II (game 7)') is True
    clock(1)
    apply_progress.begin('fetch', source='RAWG')
    with apply_progress.download('/x/boxart/a.png', 0):
        clock(4)
    with apply_progress.step('process'):
        clock(6)
    clock(7)
    apply_progress.step_done()
    clock(8)
    apply_progress.begin('search', source='IGDB')
    clock(9)
    apply_progress.step_done()
    apply_progress.begin('ai')
    clock(13)
    apply_progress.step_done()
    apply_progress.begin('save')
    clock(13.5)
    apply_progress.step_done()
    clock(14)
    apply_progress.timing_end()

    assert _timing_lines(caplog) == [
        'Scrape timing, Lufia II (game 7): 14.0s total; prepare 1.0s, '
        'lead RAWG 1.0s, media download 3.0s, image processing 2.0s, '
        'other 1.5s, fallback IGDB 1.0s, AI 4.0s, save 0.5s']


def test_timed_section_and_no_progress_task_needed(clock, caplog):
    caplog.set_level(logging.INFO, logger='services.apply_progress')
    assert apply_progress._current.get() is None
    clock(0)
    apply_progress.timing_start('g')
    with apply_progress.timed('search'):
        clock(3)
    apply_progress.timing_end()
    assert _timing_lines(caplog) == ['Scrape timing, g: 3.0s total; search 3.0s']


def test_worker_thread_time_is_listed_apart(clock, caplog):
    caplog.set_level(logging.INFO, logger='services.apply_progress')
    clock(0)
    apply_progress.timing_start('g')
    apply_progress.begin('search', source='IGDB')

    def worker():
        with apply_progress.download('/x/screenshots/s.png', 0):
            clock(5)
    ctx = contextvars.copy_context()
    t = threading.Thread(target=ctx.run, args=(worker,))
    t.start()
    t.join()
    apply_progress.timing_end()
    # The worker's time overlaps the game thread's, so it is listed apart.
    assert _timing_lines(caplog) == [
        'Scrape timing, g: 5.0s total; fallback IGDB 5.0s; '
        'worker threads, overlapping: media download 5.0s']


def test_inner_start_leaves_the_outer_timer_alone(clock, caplog):
    caplog.set_level(logging.INFO, logger='services.apply_progress')
    clock(0)
    assert apply_progress.timing_start('outer') is True
    assert apply_progress.timing_start('inner') is False
    clock(2)
    apply_progress.timing_end()
    assert _timing_lines(caplog) == ['Scrape timing, outer: 2.0s total; prepare 2.0s']


def test_end_without_start_logs_nothing(caplog):
    caplog.set_level(logging.INFO, logger='services.apply_progress')
    apply_progress.timing_end()
    assert _timing_lines(caplog) == []


def test_apply_logs_one_line_unless_a_bulk_timer_owns_it(monkeypatch, clock, caplog):
    caplog.set_level(logging.INFO, logger='services.apply_progress')
    import scraper.hybrid_scraper as hs
    from services.game_metadata_service import apply_hybrid_metadata_to_game

    def fake_apply(**kw):
        clock(0)
        apply_progress.begin('fetch', source='IGDB')
        clock(2)
        apply_progress.step_done()
        return {'success': True}
    monkeypatch.setattr(hs, 'apply_hybrid_metadata', fake_apply)

    apply_hybrid_metadata_to_game(5, 'igdb', 1, 'snes', primary_data={'id': 1})
    lines = _timing_lines(caplog)
    assert len(lines) == 1 and lines[0].startswith('Scrape timing, game 5:')
    assert 'lead IGDB' in lines[0]

    caplog.clear()
    apply_progress.timing_start('bulk')
    apply_hybrid_metadata_to_game(5, 'igdb', 1, 'snes', primary_data={'id': 1})
    assert _timing_lines(caplog) == []
    apply_progress.timing_end()
    assert len(_timing_lines(caplog)) == 1
