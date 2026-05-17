# Tests for alternate-title fallback in scraper/hltb_lookup.py

from unittest.mock import patch

from scraper import hltb_lookup


def _mk_hltb_result(name, game_id=1, comp_main=36000, platform='NES'):
    """Build a fake HLTB API result row."""
    return {
        'game_id': game_id,
        'game_name': name,
        'comp_main': comp_main,
        'comp_plus': comp_main + 3600,
        'comp_100': comp_main + 7200,
        'profile_platform': platform,
        'release_world': 1991,
        'profile_dev': 'Natsume',
    }


class TestAltTitleFallback:
    def test_primary_hit_skips_alternates(self):
        """If the primary title already matches well, alternates aren't tried."""
        calls = []

        def fake_search(title, platform='', year=None):
            calls.append(title)
            return [_mk_hltb_result('Super Mario World')]

        with patch.object(hltb_lookup, '_search_hltb', side_effect=fake_search):
            result = hltb_lookup.lookup_playtime(
                'Super Mario World',
                system_folder='snes',
                alternate_titles=['Super Mario Bros. 4'],
            )

        assert result is not None
        assert result['match_name'] == 'Super Mario World'
        assert result['matched_via_alternate'] is False
        assert result['search_term_used'] == 'Super Mario World'
        # Should have stopped on the first step (platform+... search, good match)
        # — no alt title attempted.
        assert 'Super Mario Bros. 4' not in calls

    def test_fallback_to_alternate_title(self):
        """Primary title with no good match, alt title gets a near-exact hit."""

        def fake_search(title, platform='', year=None):
            # HLTB doesn't know 'Action in New York' — returns unrelated stuff.
            if title == 'Action in New York':
                return [_mk_hltb_result('Action Fighter', game_id=99)]
            # It DOES know the US title.
            if title == 'S.C.A.T.: Special Cybernetic Attack Team':
                return [_mk_hltb_result(
                    'S.C.A.T.: Special Cybernetic Attack Team', game_id=5678
                )]
            return []

        with patch.object(hltb_lookup, '_search_hltb', side_effect=fake_search):
            result = hltb_lookup.lookup_playtime(
                'Action in New York',
                system_folder='nes',
                alternate_titles=[
                    'S.C.A.T.: Special Cybernetic Attack Team',
                    'Final Mission',
                ],
            )

        assert result is not None
        assert result['game_id'] == 5678
        assert result['match_name'] == 'S.C.A.T.: Special Cybernetic Attack Team'
        assert result['matched_via_alternate'] is True
        assert result['search_term_used'] == 'S.C.A.T.: Special Cybernetic Attack Team'

    def test_alternate_title_equal_to_primary_skipped(self):
        """An alt title equal to the primary (case-insensitive) shouldn't re-search."""
        calls = []

        def fake_search(title, platform='', year=None):
            calls.append(title)
            return [_mk_hltb_result('Doki Doki Panic', game_id=7)]

        with patch.object(hltb_lookup, '_search_hltb', side_effect=fake_search):
            hltb_lookup.lookup_playtime(
                'Doki Doki Panic',
                system_folder='nes',
                alternate_titles=['doki doki panic', 'DOKI DOKI PANIC'],
            )

        # Only the primary title should have been searched (once per step).
        # Any attempt to re-search the same title would count additional times.
        unique_titles = set(calls)
        assert unique_titles == {'Doki Doki Panic'}

    def test_no_results_anywhere_returns_none(self):
        """If neither primary nor alternates match, return None."""
        with patch.object(hltb_lookup, '_search_hltb', return_value=[]):
            result = hltb_lookup.lookup_playtime(
                'Totally Unknown Game',
                system_folder='nes',
                alternate_titles=['Also Unknown'],
            )
        assert result is None

    def test_alternates_none_still_works(self):
        """Passing alternate_titles=None is equivalent to omitting it."""

        def fake_search(title, platform='', year=None):
            return [_mk_hltb_result('Contra')]

        with patch.object(hltb_lookup, '_search_hltb', side_effect=fake_search):
            result = hltb_lookup.lookup_playtime(
                'Contra',
                system_folder='nes',
                alternate_titles=None,
            )

        assert result is not None
        assert result['matched_via_alternate'] is False

    def test_better_primary_beats_weaker_alt(self):
        """Primary with mediocre match shouldn't be replaced by a worse alt match."""

        def fake_search(title, platform='', year=None):
            if title == 'Mega Man':
                return [_mk_hltb_result('Mega Man Zero')]  # partial match
            if title == 'Rockman':
                return [_mk_hltb_result('Rockman Dash')]  # also partial
            return []

        with patch.object(hltb_lookup, '_search_hltb', side_effect=fake_search):
            result = hltb_lookup.lookup_playtime(
                'Mega Man',
                system_folder='nes',
                alternate_titles=['Rockman'],
            )

        assert result is not None
        # "Mega Man" vs "Mega Man Zero" scores higher than
        # "Rockman" vs "Rockman Dash", so primary should win.
        assert result['match_name'] == 'Mega Man Zero'
        assert result['matched_via_alternate'] is False

    def test_search_exception_returns_none(self):
        """COV-1: if `_search_hltb` raises, the top-level try/except in
        `lookup_playtime` must swallow it and return None — never propagate
        the error to the caller. A regression here would crash the scraper
        on any network blip instead of degrading gracefully."""

        def boom(title, platform='', year=None):
            raise RuntimeError('network down')

        with patch.object(hltb_lookup, '_search_hltb', side_effect=boom):
            result = hltb_lookup.lookup_playtime(
                'Anything',
                system_folder='nes',
                alternate_titles=['Also Anything'],
            )

        assert result is None
