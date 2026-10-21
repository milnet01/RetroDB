# =============================================================================
# PASS-59-134 — the game page's Apply fetches ticked results by ID
# =============================================================================
# The results are already on screen, so Apply must not search for them again.
# Ticked results are fetched by their ID as is; with none ticked, only the
# clicked source and AI fill gaps (user decision, 2026-10-21).
# =============================================================================

import contextlib

import pytest

from tests._util import REPO_ROOT  # noqa: F401  (ensures sys.path is set)


@pytest.fixture
def hybrid(monkeypatch):
    from scraper import hybrid_scraper
    monkeypatch.setattr(hybrid_scraper, 'load_scraper_settings', lambda: {
        'priority': ['esde', 'tgdb', 'igdb', 'ai'], 'enabled': {},
    })
    return hybrid_scraper


def test_no_tick_leaves_only_ai_as_a_fallback(hybrid):
    assert hybrid._fallback_order('igdb', {}, True, []) == ['ai']


def test_without_restriction_every_other_source_falls_back(hybrid):
    assert hybrid._fallback_order('igdb', {}, False, []) == ['esde', 'tgdb', 'ai']


def _lookup(user_ticked):
    return {
        'title': 'Alone in the Dark: The New Nightmare',
        'system_folder': 'psx',
        'secondary_sources': [{'source': 'esde', 'id': './Alone.chd',
                               'name': 'Alone in the Dark 2'}],
        'user_ticked': user_ticked,
    }


def test_esde_fetches_a_ticked_path_without_searching(hybrid, monkeypatch):
    """The ticked result names another game; the user's tick still wins."""
    from scraper import scrape_esde
    fetched = []

    def no_search(*a, **k):
        raise AssertionError('searched again')

    monkeypatch.setattr(scrape_esde, 'search_esde_games', no_search)
    monkeypatch.setattr(scrape_esde, 'fetch_esde_game_details',
                        lambda path, folder: fetched.append((path, folder)) or {'name': 'x'})
    assert hybrid._fetch_esde(_lookup(True)) == {'name': 'x'}
    assert fetched == [('./Alone.chd', 'psx')]


def test_a_bulk_result_with_a_differing_name_is_searched_afresh(hybrid, monkeypatch):
    from scraper import scrape_esde
    searched = []
    monkeypatch.setattr(scrape_esde, 'search_esde_games',
                        lambda title, folder, limit: searched.append(title) or [])
    assert hybrid._fetch_esde(_lookup(False)) is None
    assert searched == ['Alone in the Dark: The New Nightmare']


def test_an_empty_selection_restricts_the_apply(monkeypatch):
    from services import game_metadata_service as svc
    from scraper import hybrid_scraper
    calls = []
    monkeypatch.setattr(hybrid_scraper, 'apply_hybrid_metadata',
                        lambda **k: calls.append(k) or {'success': True})
    monkeypatch.setattr(svc, 'upscale_later', lambda _id: contextlib.nullcontext())
    svc.apply_hybrid_metadata_to_game(1, 'igdb', '5', 'snes', explicit_secondary=[])
    assert calls[0]['restrict_to_selected'] is True
    assert calls[0]['secondary_sources'] == []
