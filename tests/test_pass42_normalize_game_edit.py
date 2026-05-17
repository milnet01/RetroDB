# =============================================================================
# Pass 42.1 — normalize_game_edit helper (single source of truth for the
# form-POST and JSON game-edit paths)
# =============================================================================
# Regression pins for the dict-in / dict-out helper that owns the strip +
# empty-as-None / release_date validation / players coercion / rating
# cross-map / sort_title / similar_games-rejoin transforms.  Two prior
# divergences are now collapsed: the form-POST cross-mapped ratings + ran
# generate_sort_title; api_game_edit (JSON) did neither.
# =============================================================================

import os
import sys

import pytest

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from services.game_metadata_service import normalize_game_edit


class TestNormalizeStrip:
    def test_strips_whitespace_on_strings(self):
        out = normalize_game_edit({'title': '  Final Fantasy IX  '})
        assert out['title'] == 'Final Fantasy IX'

    def test_empty_string_to_none(self):
        out = normalize_game_edit({'publisher': '   '})
        assert out['publisher'] is None

    def test_keys_absent_from_payload_stay_absent(self):
        """Unprovided fields must NOT appear in the output dict — the JSON
        edit path filters by `if field in normalized` and would otherwise
        write None over curated values the caller didn't ask to update."""
        out = normalize_game_edit({'title': 'X'})
        assert 'publisher' not in out
        assert 'genre' not in out
        assert 'esrb_rating' not in out

    def test_does_not_mutate_caller_dict(self):
        payload = {'title': '  X  ', 'players': '1-4'}
        snapshot = dict(payload)
        normalize_game_edit(payload)
        assert payload == snapshot, 'helper must not mutate caller dict'


class TestNormalizeReleaseDate:
    def test_accepts_yyyy_mm_dd(self):
        out = normalize_game_edit({'release_date': '1996-04-27'})
        assert out['release_date'] == '1996-04-27'

    def test_slashes_converted_to_dashes(self):
        out = normalize_game_edit({'release_date': '1996/04/27'})
        assert out['release_date'] == '1996-04-27'

    def test_junk_to_none(self):
        out = normalize_game_edit({'release_date': 'not-a-date'})
        assert out['release_date'] is None

    def test_invalid_calendar_to_none(self):
        # Feb 30 doesn't exist — strptime rejects, helper returns None.
        out = normalize_game_edit({'release_date': '1996-02-30'})
        assert out['release_date'] is None


class TestNormalizePlayers:
    """Pinned the Pass 40.6 invariant: players is INTEGER, weak typing
    must not let "1-4" leak into the column."""

    @pytest.mark.parametrize("val,expected", [
        ('1-4', 4),     # range → max
        ('2', 2),       # plain numeric string
        (2, 2),         # int passthrough
        ('', None),     # empty → cleared
        ('unknown', None),  # junk → cleared (so COALESCE preserves curated)
    ])
    def test_players_coercion(self, val, expected):
        assert normalize_game_edit({'players': val})['players'] == expected


class TestNormalizeRatingsCrossMap:
    """Cross-mapping must only fire on rating keys present in the
    payload — JSON callers updating one rating must not have the other
    seven systems written underneath them."""

    def test_single_rating_does_not_trigger_other_seven(self):
        out = normalize_game_edit({'esrb_rating': 'T'})
        assert out['esrb_rating'] == 'T'
        for k in ('pegi_rating', 'cero_rating', 'usk_rating', 'acb_rating',
                  'fpb_rating', 'grac_rating', 'classind_rating'):
            assert k not in out, (
                f'cross-map must not write {k} when caller passed only esrb_rating'
            )

    def test_full_set_cross_maps_empties(self):
        # Form-POST shape: all 8 keys present; only ESRB filled.  PEGI etc
        # should be filled by the cross-map.
        payload = {
            'esrb_rating': 'T',
            'pegi_rating': '', 'cero_rating': '', 'usk_rating': '',
            'acb_rating': '', 'fpb_rating': '', 'grac_rating': '',
            'classind_rating': '',
        }
        out = normalize_game_edit(payload)
        assert out['esrb_rating'] == 'T'
        # PEGI should fill from ESRB T (12+) — we don't pin the exact value
        # (that's tested in services/game_utils tests), only that it's not
        # None.  This proves the cross-map fired.
        assert out['pegi_rating'], (
            'cross-map must fill empty PEGI from filled ESRB when both '
            'keys are in the payload'
        )

    def test_pegi_empty_stays_none_when_only_pegi_passed(self):
        # Caller asks to clear PEGI; no other ratings in payload — output
        # PEGI must be None (clear), not magically filled.
        out = normalize_game_edit({'pegi_rating': ''})
        assert out['pegi_rating'] is None


class TestNormalizeSortTitle:
    def test_auto_generates_when_title_given(self):
        out = normalize_game_edit({'title': 'Final Fantasy IX'})
        # generate_sort_title pads roman numerals to two-digit arabic, so
        # "IX" → "09".  Anchor the exact expected output — the prior
        # disjunctive (`!= 'Final Fantasy IX' or 'IX' not in out['title']`)
        # was unfalsifiable in practice (c-006 A-2 finding).
        assert out['sort_title'] == 'Final Fantasy 09', (
            f"sort_title must transform roman numerals to padded arabic, "
            f"got {out['sort_title']!r}"
        )

    def test_explicit_sort_title_preserved(self):
        out = normalize_game_edit({
            'title': 'Final Fantasy IX',
            'sort_title': 'Final Fantasy 9',
        })
        assert out['sort_title'] == 'Final Fantasy 9'

    def test_no_title_no_sort_title(self):
        out = normalize_game_edit({'publisher': 'Square'})
        assert 'sort_title' not in out


class TestNormalizeSimilarGames:
    def test_rejoins_with_single_space(self):
        out = normalize_game_edit({
            'similar_games': 'Final Fantasy VIII,  Final Fantasy X  ,Chrono Trigger',
        })
        assert out['similar_games'] == 'Final Fantasy VIII, Final Fantasy X, Chrono Trigger'

    def test_drops_empty_entries(self):
        out = normalize_game_edit({'similar_games': 'A,, , B'})
        assert out['similar_games'] == 'A, B'

    def test_empty_to_none(self):
        out = normalize_game_edit({'similar_games': ''})
        assert out['similar_games'] is None
