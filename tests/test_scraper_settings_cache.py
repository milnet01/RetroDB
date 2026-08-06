"""Contracts for the cached `scraper_settings.json` reader (Pass 57.5).

Pass 57.5 routed the request-path readers of `scraper_settings.json` through
`scraper_manager.load_scraper_settings()` instead of a fresh `open()` per
request. The 30-second TTL cache those readers now sit behind brings two
hazards that did not exist while every reader re-parsed the file, and both are
silent — nothing fails loudly, the wrong value simply gets used:

  * **Cache aliasing.** The GET handler mutates what it is handed: it masks
    `api_keys` down to `***<last4>` before returning them. Handing out the
    cached dict itself would replace every real key with its display mask for
    the rest of the TTL — the scrapers would then authenticate with `***`.
  * **Post-save staleness.** A save writes the file but the cache would keep
    answering from the pre-save snapshot for up to 30 s, so the Scraper Config
    page could report the value the user just overwrote.

The third test pins the file path itself: the writers anchor to
`config.BASE_DIR` and the loader used to derive its own repo-root path, which
agree from a source checkout and diverge inside a PyInstaller bundle.
"""
import json

import pytest

import config
import scraper.scraper_manager as sm


@pytest.fixture
def settings_file(tmp_path, monkeypatch):
    """Point the loader at a throwaway settings file with a clean cache.

    `SCRAPER_SETTINGS_FILE` is a module constant with no env override, so it is
    monkeypatched directly (the pattern tests/test_settings_bind_config.py uses
    for the sibling store). The cache is cleared on both sides of the test so
    neither a previously-cached real settings file leaks in nor this file's
    contents leak out.
    """
    path = tmp_path / 'scraper_settings.json'
    path.write_text(json.dumps({
        'priority': ['igdb', 'tgdb'],
        'enabled': {'igdb': True, 'tgdb': False},
        'api_keys': {'tgdb': 'REAL-KEY-1234'},
    }))
    monkeypatch.setattr(sm, 'SCRAPER_SETTINGS_FILE', str(path))
    sm.invalidate_scraper_settings_cache()
    yield path
    sm.invalidate_scraper_settings_cache()


class TestReturnsACopy:
    """A caller mutating the result must not reach the shared cache."""

    def test_mutating_the_result_does_not_affect_the_next_read(self, settings_file):
        first = sm.load_scraper_settings()
        assert first['api_keys']['tgdb'] == 'REAL-KEY-1234'

        # Exactly what routes/scraper.py::api_get_scraper_settings does.
        first['api_keys']['tgdb'] = '***1234'
        first['priority'].append('screenscraper')
        first['enabled']['igdb'] = False

        second = sm.load_scraper_settings()
        assert second['api_keys']['tgdb'] == 'REAL-KEY-1234'
        assert second['priority'] == ['igdb', 'tgdb']
        assert second['enabled']['igdb'] is True

    def test_nested_containers_are_copied_not_shared(self, settings_file):
        """A shallow copy would pass the test above for `priority` reassignment
        but still share the nested `api_keys` dict — assert identity directly so
        a regression to `dict(...)` is caught rather than passing by luck."""
        first = sm.load_scraper_settings()
        second = sm.load_scraper_settings()
        assert first is not second
        assert first['api_keys'] is not second['api_keys']
        assert first['enabled'] is not second['enabled']
        assert first['priority'] is not second['priority']


class TestInvalidation:
    """A write must be visible to the next read, not 30 seconds later."""

    def test_cached_read_does_not_see_a_file_change(self, settings_file):
        """The TTL is real — this is the behaviour invalidation exists to fix,
        asserted so the next test is not vacuously true."""
        assert sm.load_scraper_settings()['priority'] == ['igdb', 'tgdb']
        settings_file.write_text(json.dumps({'priority': ['rawg']}))
        assert sm.load_scraper_settings()['priority'] == ['igdb', 'tgdb']

    def test_invalidate_forces_a_reread(self, settings_file):
        assert sm.load_scraper_settings()['priority'] == ['igdb', 'tgdb']
        settings_file.write_text(json.dumps({'priority': ['rawg']}))
        sm.invalidate_scraper_settings_cache()
        assert sm.load_scraper_settings()['priority'] == ['rawg']

    def test_both_writers_invalidate(self):
        """Every `atomic_write_json` of the settings file is followed by an
        invalidation. A new writer added without one reintroduces the stale
        window, and it would not fail any behavioural test that does not
        happen to exercise that particular route."""
        import routes.scraper as routes_scraper
        from tests._util import read_module_source

        source = read_module_source(routes_scraper)
        writes = source.count('atomic_write_json(SCRAPER_SETTINGS_FILE')
        invalidations = source.count('invalidate_scraper_settings_cache()')
        assert writes == 2, f'expected 2 settings writers, found {writes}'
        # One call per writer, plus the import line is not a call.
        assert invalidations == writes, (
            f'{writes} writers but {invalidations} invalidations — '
            'every write of scraper_settings.json must bust the cache'
        )


class TestPathAgreement:
    """Loader and writers must resolve to the same file in every build shape."""

    def test_loader_and_route_agree_on_the_settings_path(self):
        import routes.scraper as routes_scraper

        assert sm.SCRAPER_SETTINGS_FILE == routes_scraper.SCRAPER_SETTINGS_FILE

    def test_path_is_anchored_to_base_dir(self):
        """Anchoring matters only where BASE_DIR stops equalling the repo root —
        a frozen bundle, where BASE_DIR sits next to the launcher and this
        module's __file__ sits under _internal/. Assert the anchor rather than
        the resolved string, which are the same value from a checkout."""
        import os

        assert sm.SCRAPER_SETTINGS_FILE == os.path.join(
            config.BASE_DIR, 'data', 'scraper_settings.json'
        )
