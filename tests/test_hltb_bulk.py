# Tests for services/jobs/hltb_bulk.py classifier + helpers

import json

import pytest

from services.jobs.hltb_bulk import (
    classify_match,
    _format_playtime_str,
    _extract_alt_titles_list,
)


class TestClassifyMatch:
    @pytest.mark.parametrize('result,expected', [
        # None result → no-result skip classification
        (None, 'skip_no_result'),
        # High-confidence primary → auto-apply
        ({'match_confidence': 100, 'matched_via_alternate': False}, 'auto_apply'),
        # At threshold (95) → still auto-apply (inclusive boundary)
        ({'match_confidence': 95, 'matched_via_alternate': False}, 'auto_apply'),
        # Below threshold → queue for manual review
        ({'match_confidence': 80, 'matched_via_alternate': False}, 'queue_low_conf'),
        # Alt-title match always queues regardless of confidence (high)
        ({'match_confidence': 100, 'matched_via_alternate': True}, 'queue_alt'),
        # Alt-match takes precedence over low-confidence classification
        ({'match_confidence': 70, 'matched_via_alternate': True}, 'queue_alt'),
        # Absent confidence key treated as zero → queue_low_conf for non-alt
        ({'matched_via_alternate': False}, 'queue_low_conf'),
    ])
    def test_classify_match(self, result, expected):
        assert classify_match(result, 'X', 95) == expected


class TestFormatPlaytimeStr:
    def test_all_three(self):
        """All three playtimes present → joined with ' | ' separator in the
        canonical 'Main | Main+Extras | 100%' order. format_playtime drops
        trailing .0 from whole-hour values (8.0 → '8 hrs', not '8.0 hrs')."""
        s = _format_playtime_str(6.5, 8.0, 12.0)
        assert s == 'Main: 6.5 hrs | Main+Extras: 8 hrs | 100%: 12 hrs'

    def test_main_and_extra_no_completionist(self):
        """COV-2: two-part join (no completionist) must use a single ' | '
        separator — no trailing pipe, no missing piece."""
        s = _format_playtime_str(6.5, 8.0, None)
        assert s == 'Main: 6.5 hrs | Main+Extras: 8 hrs'

    def test_only_main(self):
        s = _format_playtime_str(6.5, None, None)
        assert s == 'Main: 6.5 hrs'

    def test_all_none(self):
        assert _format_playtime_str(None, None, None) is None

    def test_zero_treated_as_missing(self):
        """A zero playtime is the API's 'no data' sentinel — the formatter
        must treat 0 the same as None and skip that part of the string."""
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
        payload = json.dumps([
            {'title': 'S.C.A.T.', 'region': 'US'},
            {'title': 'Final Mission', 'region': 'JP'},
        ])
        assert _extract_alt_titles_list(payload) == ['S.C.A.T.', 'Final Mission']

    def test_skips_entries_without_title(self):
        payload = json.dumps([
            {'region': 'US'},
            {'title': ''},
            {'title': 'Valid'},
            'not a dict',
        ])
        assert _extract_alt_titles_list(payload) == ['Valid']

    def test_strips_whitespace(self):
        payload = json.dumps([{'title': '  Padded  '}])
        assert _extract_alt_titles_list(payload) == ['Padded']
