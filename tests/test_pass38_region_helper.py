# =============================================================================
# Pass 38.1 (partial) — _normalize_region helper
# =============================================================================
# Pass 38.1's normalize sub-block had two near-identical settings-load /
# default-fallback branches inline (one for multi-value reduction, one for
# empty-region fallback). Pass 38.1 (partial) extracted both into a single
# helper that loads settings once.  These tests pin the contract:
#   - Multi-value ('USA, Europe, Japan'): pick first that matches the
#     configured region_options, else default_region.
#   - Empty / missing: use default_region, record 'region (default)' in
#     filled_fields.
#   - Single-value matching one of region_options: leave untouched.
#   - Settings-load failure: fall back to ('usa','europe','japan','world')
#     option set + 'USA' default.
# =============================================================================

import pytest

from tests._util import REPO_ROOT as _REPO_ROOT  # noqa: F401


@pytest.fixture
def stub_settings(monkeypatch):
    """Make `from settings_manager import load_settings` return a known dict.

    Returns a factory: call `stub_settings({...})` from inside the test to
    set the payload. The fixture also installs a sane default payload up
    front so a test that forgets to call the factory still gets a defined
    `load_settings` and produces a clear assertion failure rather than an
    `AttributeError: module 'settings_manager' has no attribute
    'load_settings'` (test-audit FIX-2).
    """
    import sys as _sys
    import types

    fake_module = types.ModuleType('settings_manager')

    # Sane default — covers tests that don't override and gives a
    # deterministic baseline for ones that do.
    def _default_load():
        return {'region_options': ['USA'], 'default_region': 'USA'}

    fake_module.load_settings = _default_load

    def _factory(payload):
        def _load_settings():
            return dict(payload)
        fake_module.load_settings = _load_settings
        return fake_module

    monkeypatch.setitem(_sys.modules, 'settings_manager', fake_module)
    return _factory


class TestNormalizeRegion:
    def test_multivalue_reduces_to_first_match(self, stub_settings):
        from scraper import hybrid_scraper

        stub_settings({
            'region_options': ['USA', 'Europe', 'Japan', 'World'],
            'default_region': 'USA',
        })
        metadata = {'region': 'World, Europe, USA'}
        result = {'filled_fields': []}
        hybrid_scraper._normalize_region(metadata, result)
        # 'World' is first match in region_options (case-insensitive).
        assert metadata['region'] == 'World'
        # No (default) tag — region was present, just multi-valued.
        assert 'region (default)' not in result['filled_fields']

    def test_multivalue_no_match_uses_default(self, stub_settings):
        """Multi-value where no part matches region_options falls through
        to default_region. Empty-string match returns next iter sentinel
        (None), so `matched or default_region` resolves correctly."""
        from scraper import hybrid_scraper

        stub_settings({
            'region_options': ['USA', 'Europe'],
            'default_region': 'USA',
        })
        metadata = {'region': 'Mars, Pluto'}
        result = {'filled_fields': []}
        hybrid_scraper._normalize_region(metadata, result)
        assert metadata['region'] == 'USA'
        # Multi-value — not a "default fill", just a reduction with fallback;
        # the original inline didn't tag either, helper preserves that.
        assert 'region (default)' not in result['filled_fields']

    def test_empty_region_filled_with_default_and_tagged(self, stub_settings):
        from scraper import hybrid_scraper

        stub_settings({
            'region_options': ['USA', 'Europe', 'Japan'],
            'default_region': 'Europe',
        })
        metadata = {'region': ''}
        result = {'filled_fields': []}
        hybrid_scraper._normalize_region(metadata, result)
        assert metadata['region'] == 'Europe'
        assert 'region (default)' in result['filled_fields']

    def test_missing_region_key_filled_with_default(self, stub_settings):
        """metadata may not have 'region' key at all (None / missing).
        Helper must use .get() so it doesn't KeyError."""
        from scraper import hybrid_scraper

        stub_settings({
            'region_options': ['USA'],
            'default_region': 'USA',
        })
        metadata = {}
        result = {'filled_fields': []}
        hybrid_scraper._normalize_region(metadata, result)
        assert metadata['region'] == 'USA'
        assert 'region (default)' in result['filled_fields']

    def test_single_value_left_untouched(self, stub_settings):
        from scraper import hybrid_scraper

        stub_settings({
            'region_options': ['USA', 'Europe'],
            'default_region': 'USA',
        })
        metadata = {'region': 'Europe'}
        result = {'filled_fields': []}
        hybrid_scraper._normalize_region(metadata, result)
        assert metadata['region'] == 'Europe'
        assert result['filled_fields'] == []

    def test_settings_load_failure_falls_back_to_hardcoded_defaults(
        self, monkeypatch
    ):
        """If `from settings_manager import load_settings` raises, helper
        must fall back to ('usa','europe','japan','world') options + 'USA'
        default — same hardcoded fallback the inline version used."""
        import sys as _sys
        import types

        fake_module = types.ModuleType('settings_manager')
        def _bad():
            raise RuntimeError("settings unavailable")
        fake_module.load_settings = _bad
        monkeypatch.setitem(_sys.modules, 'settings_manager', fake_module)

        from scraper import hybrid_scraper

        # Empty region — should pick up the hardcoded 'USA' default.
        metadata = {'region': ''}
        result = {'filled_fields': []}
        hybrid_scraper._normalize_region(metadata, result)
        assert metadata['region'] == 'USA'
        assert 'region (default)' in result['filled_fields']
