"""Contracts for the two concurrent scraper paths (Pass 57.7 item 5).

Pass 55.1 fanned `ScraperManager.search_games` out over five sources, and Pass
55.3 fanned screenshot downloads out over a thread pool. Both traded a
straight-line execution order for a thread pool, and both therefore owe the
same two guarantees — which nothing was pinning:

  * **Order determinism.** What comes back must not depend on which worker
    finished first. For screenshots that matters more than tidiness: the dedup
    step decides *which* of two near-identical images survives, so completion
    order leaking into it makes the kept screenshot vary run to run.
  * **Per-source failure isolation.** One source raising must cost that
    source's results and nothing else.

Both are asserted by making completion order the *reverse* of the declared
order, so a naive as-completed reassembly cannot accidentally pass.
"""
import threading
import time

import pytest

import scraper.metadata_merger as merger
import scraper.scraper_manager as sm

# The canonical reassembly order search_games promises, by `source` value.
CANONICAL_SOURCES = ['esde', 'thegamesdb', 'igdb', 'rawg', 'screenscraper']


# ---------------------------------------------------------------------------
# _download_screenshots_parallel — Pass 55.3
# ---------------------------------------------------------------------------

@pytest.fixture
def dedup_calls(monkeypatch):
    """Record keep_screenshot_if_unique calls; keep everything it is given."""
    calls = []

    def _keep(local_path, filename, existing_hashes, source_label):
        calls.append(filename)
        existing_hashes.add(filename)
        return True

    monkeypatch.setattr(merger, 'keep_screenshot_if_unique', _keep)
    return calls


def _slow_job(name, delay):
    def _job():
        time.sleep(delay)
        return name
    return _job


def test_dedup_runs_in_job_order_not_completion_order(dedup_calls):
    """Jobs finish in reverse order; dedup must still see them 1, 2, 3.

    The dedup step mutates a shared hash set and deletes the losing duplicate,
    so if completion order reached it, which screenshot survives would differ
    between runs on the same inputs.
    """
    jobs = [_slow_job('first.png', 0.15),
            _slow_job('second.png', 0.10),
            _slow_job('third.png', 0.01)]

    kept = merger._download_screenshots_parallel(jobs, set(), 'TEST')

    assert kept == ['first.png', 'second.png', 'third.png']
    assert dedup_calls == ['first.png', 'second.png', 'third.png'], \
        'dedup must be driven in job order, single-threaded'


def test_downloads_actually_run_concurrently(dedup_calls):
    """The point of the pool. A barrier all four jobs must reach before any
    may return — under sequential execution the first job blocks forever and
    the barrier times out, so this cannot pass by accident."""
    barrier = threading.Barrier(4, timeout=5)

    def _job(name):
        def _run():
            barrier.wait()
            return name
        return _run

    names = ['a.png', 'b.png', 'c.png', 'd.png']
    kept = merger._download_screenshots_parallel(
        [_job(n) for n in names], set(), 'TEST')

    assert kept == names, 'a timed-out barrier means the downloads were serial'


def test_one_crashing_download_does_not_sink_the_batch(dedup_calls):
    """A worker that raises costs its own screenshot only, and the survivors
    keep their relative order."""
    def _boom():
        raise RuntimeError('connection reset')

    jobs = [_slow_job('first.png', 0.10), _boom, _slow_job('third.png', 0.01)]

    kept = merger._download_screenshots_parallel(jobs, set(), 'TEST')

    assert kept == ['first.png', 'third.png']


def test_a_failed_download_is_skipped_not_deduped(dedup_calls):
    """Jobs signal failure with a falsy return, which must never reach dedup
    (it would build a path out of None and stat it)."""
    jobs = [_slow_job('first.png', 0.01), lambda: None, lambda: '']

    kept = merger._download_screenshots_parallel(jobs, set(), 'TEST')

    assert kept == ['first.png']
    assert dedup_calls == ['first.png']


def test_no_jobs_short_circuits(dedup_calls):
    assert merger._download_screenshots_parallel([], set(), 'TEST') == []
    assert dedup_calls == []


# ---------------------------------------------------------------------------
# ScraperManager.search_games — Pass 55.1
# ---------------------------------------------------------------------------

def _result(source, title='Game'):
    # Every source scores 50 so the final sort cannot reorder them. ES-DE
    # needs it set here rather than via a calculate_* stub: search_games
    # scores the other four itself but takes ES-DE's score as given.
    #
    # No 'platform' / 'platforms' keys: those would pull the ES-DE platform
    # normaliser in, which is not what these tests are about.
    return {'title': title, 'source': source, 'scraper': source, 'score': 50}


@pytest.fixture
def stub_sources(monkeypatch):
    """Wire all five search sources to controllable stubs.

    Returns a dict of source-key -> delay that a test can rewrite before
    calling search_games. Every source scores identically and the priority
    list is empty, so the final sort (stable, by score) cannot reorder them —
    what remains in the output IS the reassembly order.
    """
    delays = {'esde': 0.20, 'tgdb': 0.15, 'igdb': 0.10, 'rawg': 0.05,
              'screenscraper': 0.01}
    raisers = set()

    def _make(key, source_value):
        def _search(*args, **kwargs):
            if key in raisers:
                raise RuntimeError(f'{key} is down')
            time.sleep(delays[key])
            return [_result(source_value)]
        return _search

    monkeypatch.setattr(sm, 'ESDE_AVAILABLE', True)
    monkeypatch.setattr(sm, 'RAWG_AVAILABLE', True)
    monkeypatch.setattr(sm, 'SCREENSCRAPER_AVAILABLE', True)
    monkeypatch.setattr(sm, 'load_scraper_enabled',
                        lambda: {k: True for k in
                                 ('esde', 'tgdb', 'igdb', 'rawg', 'screenscraper')})
    # Empty priority list => no priority boost => every score stays equal.
    monkeypatch.setattr(sm, 'load_scraper_priority', lambda: [])
    monkeypatch.setattr(sm, 'load_scraper_settings', lambda: {'api_keys': {
        'screenscraper_username': 'u', 'screenscraper_password': 'p',
        'screenscraper_devid': 'd', 'screenscraper_devpassword': 'dp'}})

    monkeypatch.setattr(sm, 'search_esde', _make('esde', 'esde'))
    monkeypatch.setattr(sm, 'search_tgdb', _make('tgdb', 'thegamesdb'))
    monkeypatch.setattr(sm, 'search_igdb', _make('igdb', 'igdb'))
    monkeypatch.setattr(sm, 'search_rawg', _make('rawg', 'rawg'))
    monkeypatch.setattr(sm, 'search_screenscraper',
                        _make('screenscraper', 'screenscraper'))

    # Neutralise the circuit breakers: they carry state across tests, so a
    # deliberate failure here could otherwise trip a breaker and silently skip
    # that source in an unrelated test.
    for name in ('_tgdb_breaker', '_igdb_breaker', '_rawg_breaker',
                 '_screenscraper_breaker'):
        monkeypatch.setattr(sm, name, lambda fn: fn)

    for name in ('calculate_tgdb_score', 'calculate_igdb_score',
                 'calculate_rawg_score', 'calculate_ss_score'):
        monkeypatch.setattr(sm, name, lambda *a, **kw: 50)
    monkeypatch.setattr(sm.ScraperManager, '_parse_ss_result',
                        lambda self, result, folder: dict(result))

    return {'delays': delays, 'raisers': raisers}


def test_search_reassembles_in_canonical_source_order(stub_sources):
    """ES-DE, TGDB, IGDB, RAWG, SS — regardless of who answers first.

    The stub delays are the exact reverse of the canonical order, so an
    as-completed reassembly would return them backwards.
    """
    results = sm.ScraperManager().search_games(
        'Zelda', system_name='SNES', system_folder='snes')

    assert [r['source'] for r in results] == CANONICAL_SOURCES


def test_search_order_is_stable_when_completion_order_changes(stub_sources):
    """Same call, opposite completion order: identical output."""
    first = sm.ScraperManager().search_games(
        'Zelda', system_name='SNES', system_folder='snes')

    stub_sources['delays'].update(esde=0.01, tgdb=0.05, igdb=0.10,
                                  rawg=0.15, screenscraper=0.20)
    second = sm.ScraperManager().search_games(
        'Zelda', system_name='SNES', system_folder='snes')

    assert [r['source'] for r in first] == [r['source'] for r in second]


@pytest.mark.parametrize('down', ['esde', 'tgdb', 'igdb', 'rawg',
                                  'screenscraper'])
def test_one_failing_source_costs_only_its_own_results(stub_sources, down):
    """Every source swallows and logs its own exception; the search returns
    the other four, still in canonical order."""
    stub_sources['raisers'].add(down)

    results = sm.ScraperManager().search_games(
        'Zelda', system_name='SNES', system_folder='snes')

    expected = [s for s in CANONICAL_SOURCES
                if s != ('thegamesdb' if down == 'tgdb' else down)]
    assert [r['source'] for r in results] == expected


def test_a_worker_crashing_outside_its_own_guard_is_contained(stub_sources,
                                                              monkeypatch):
    """The belt-and-braces guard around `future.result()`.

    Each worker's own try/except covers the search call, but not the enabled
    lookup that precedes it. A mapping that raises there escapes the worker
    entirely — and must still not sink the other four sources.
    """
    class _HostileEnabled(dict):
        def get(self, key, default=None):
            if key == 'esde':
                raise RuntimeError('settings blew up')
            return True

    monkeypatch.setattr(sm, 'load_scraper_enabled', _HostileEnabled)

    results = sm.ScraperManager().search_games(
        'Zelda', system_name='SNES', system_folder='snes')

    assert [r['source'] for r in results] == CANONICAL_SOURCES[1:]
