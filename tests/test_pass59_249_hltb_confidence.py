"""PASS-59-249: an HLTB match confidence is always a percent.

The lookup sends round(score * 100), so a 1% match arrives as 1 and was read
as a fraction: 100%."""
from services import hltb_service


def test_one_percent_is_one_percent():
    assert hltb_service._normalize_confidence(1) == 0.01
    assert hltb_service._normalize_confidence(85) == 0.85
    assert hltb_service._normalize_confidence([1]) == 0.01
    assert hltb_service._normalize_confidence(None) is None


def test_approving_a_one_percent_match_stores_one_percent(monkeypatch):
    written = []
    monkeypatch.setattr(hltb_service, 'execute', lambda sql, params: written.append(params))
    hltb_service.HLTBPendingQueue()._apply({
        'id': 3, 'game_id': 7, 'hltb_id': 1, 'match_name': 'X', 'match_platform': None,
        'confidence': 1, 'playtime': 5, 'main_story': 5, 'main_plus_sides': None,
        'completionist': None})
    assert 0.01 in written[0]
