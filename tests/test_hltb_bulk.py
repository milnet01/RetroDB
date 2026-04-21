# Tests for services/jobs/hltb_bulk.py classifier + helpers

from services.jobs.hltb_bulk import (
    classify_match,
    _format_playtime_str,
    _extract_alt_titles_list,
)


class TestClassifyMatch:
    def test_none_result(self):
        assert classify_match(None, 'Game', 95) == 'skip_no_result'

    def test_auto_apply_high_confidence_primary(self):
        result = {
            'match_confidence': 100,
            'matched_via_alternate': False,
        }
        assert classify_match(result, 'Super Mario World', 95) == 'auto_apply'

    def test_auto_apply_at_threshold(self):
        result = {'match_confidence': 95, 'matched_via_alternate': False}
        assert classify_match(result, 'X', 95) == 'auto_apply'

    def test_queue_low_confidence_primary(self):
        result = {'match_confidence': 80, 'matched_via_alternate': False}
        assert classify_match(result, 'X', 95) == 'queue_low_conf'

    def test_queue_alt_always_even_high_conf(self):
        """Alt-title matches always queue regardless of confidence."""
        result = {'match_confidence': 100, 'matched_via_alternate': True}
        assert classify_match(result, 'Action in New York', 95) == 'queue_alt'

    def test_queue_alt_low_conf_is_alt_not_low(self):
        """Alt-match classification wins over low-confidence classification."""
        result = {'match_confidence': 70, 'matched_via_alternate': True}
        assert classify_match(result, 'X', 95) == 'queue_alt'

    def test_missing_confidence_treated_as_zero(self):
        result = {'matched_via_alternate': False}
        assert classify_match(result, 'X', 95) == 'queue_low_conf'


class TestFormatPlaytimeStr:
    def test_all_three(self):
        s = _format_playtime_str(6.5, 8.0, 12.0)
        assert 'Main:' in s
        assert 'Main+Extras:' in s
        assert '100%:' in s

    def test_only_main(self):
        s = _format_playtime_str(6.5, None, None)
        assert s == 'Main: 6.5 hrs'

    def test_all_none(self):
        assert _format_playtime_str(None, None, None) is None

    def test_zero_treated_as_missing(self):
        assert _format_playtime_str(0, 0, 0) is None


class TestExtractAltTitlesList:
    def test_none(self):
        assert _extract_alt_titles_list(None) == []

    def test_empty_string(self):
        assert _extract_alt_titles_list('') == []

    def test_malformed_json(self):
        assert _extract_alt_titles_list('not json') == []

    def test_not_a_list(self):
        assert _extract_alt_titles_list('{"title": "x"}') == []

    def test_valid(self):
        import json
        payload = json.dumps([
            {'title': 'S.C.A.T.', 'region': 'US'},
            {'title': 'Final Mission', 'region': 'JP'},
        ])
        assert _extract_alt_titles_list(payload) == ['S.C.A.T.', 'Final Mission']

    def test_skips_entries_without_title(self):
        import json
        payload = json.dumps([
            {'region': 'US'},
            {'title': ''},
            {'title': 'Valid'},
            'not a dict',
        ])
        assert _extract_alt_titles_list(payload) == ['Valid']

    def test_strips_whitespace(self):
        import json
        payload = json.dumps([{'title': '  Padded  '}])
        assert _extract_alt_titles_list(payload) == ['Padded']
