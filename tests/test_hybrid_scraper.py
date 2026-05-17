"""Regression tests for scraper/hybrid_scraper.py (Pass 23.9).

Pins the contract that _pick_best_fallback and _pick_best_secondary use the
real `calculate_title_match_score` from scraper.match_scorer. Pass 6 split
the scorer out of scraper_manager but left two call sites referencing the
old `scraper_manager._calculate_title_match_score` attribute, which silently
raised AttributeError under the outer `except Exception`.
"""

from scraper.hybrid_scraper import _pick_best_fallback, _pick_best_secondary


def test_pick_best_fallback_returns_best_titled_result_without_attribute_error():
    results = [
        {'name': 'Castlevania II: Simon\'s Quest'},
        {'name': 'Castlevania'},
        {'name': 'Castlevania III: Dracula\'s Curse'},
    ]
    best = _pick_best_fallback(results, 'Castlevania', min_title_score=0)
    assert best is not None
    assert best['name'] == 'Castlevania'


def test_pick_best_fallback_handles_screenscraper_noms_shape():
    results = [
        {'noms': [{'region': 'us', 'text': 'Final Fantasy VII'}]},
        {'noms': [{'region': 'us', 'text': 'Final Fantasy VIII'}]},
    ]
    best = _pick_best_fallback(results, 'Final Fantasy VII', min_title_score=0)
    assert best is not None
    noms = best['noms']
    assert noms[0]['text'] == 'Final Fantasy VII'


def test_pick_best_fallback_rejects_below_min_title_score():
    results = [{'name': 'Completely Unrelated Game Title'}]
    best = _pick_best_fallback(results, 'Castlevania', min_title_score=80)
    assert best is None


def test_pick_best_secondary_returns_best_match():
    candidates = [
        {'source': 'tgdb', 'id': 1, 'name': 'Rambo III'},
        {'source': 'tgdb', 'id': 2, 'name': 'Rambo: First Blood Part II'},
    ]
    best = _pick_best_secondary(candidates, 'Rambo III', min_title_score=0)
    assert best is not None
    assert best['id'] == 1


def test_pick_best_secondary_uses_precomputed_score_when_present():
    candidates = [
        {'source': 'tgdb', 'id': 1, 'name': 'A', 'title_score': 50},
        {'source': 'tgdb', 'id': 2, 'name': 'B', 'title_score': 200},
    ]
    best = _pick_best_secondary(candidates, 'whatever', min_title_score=100)
    assert best is not None
    assert best['id'] == 2


def test_pick_best_secondary_returns_none_when_below_threshold():
    candidates = [{'source': 'tgdb', 'id': 1, 'name': 'Totally Different'}]
    best = _pick_best_secondary(candidates, 'Castlevania', min_title_score=200)
    assert best is None


def test_pick_best_fallback_returns_none_on_empty_list():
    """Empty candidate list must return None, not raise IndexError /
    StopIteration. The outer except Exception in callers would swallow
    the raise but lose the regression signal."""
    assert _pick_best_fallback([], 'Castlevania', min_title_score=0) is None


def test_pick_best_secondary_returns_none_on_empty_list():
    assert _pick_best_secondary([], 'Castlevania', min_title_score=0) is None
