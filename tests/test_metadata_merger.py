"""Characterisation tests for scraper/metadata_merger.py apply_*_to_metadata()
functions (Pass 14.3a).

These tests pin the current behaviour so future refactors (e.g. per-source
Strategy classes) can't regress silently. Image download paths are
intentionally exercised only with empty URLs — the tests stay in the
text-field / rating / merge-logic domain and skip network/filesystem work.
"""

import pytest

from scraper.metadata_merger import (
    apply_tgdb_to_metadata,
    apply_igdb_to_metadata,
    apply_rawg_to_metadata,
    apply_screenscraper_to_metadata,
    apply_ai_to_metadata,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

# Superset of every metadata key touched by any apply_* function.
_METADATA_KEYS = [
    'title', 'publisher', 'developer', 'release_date', 'description',
    'genre', 'players', 'modes',
    'esrb_rating', 'pegi_rating', 'cero_rating', 'usk_rating',
    'acb_rating', 'fpb_rating', 'grac_rating', 'classind_rating',
    'boxart', 'boxart_3d', 'screenshots', 'fanart', 'video', 'manual',
    'franchise', 'similar_games', 'playtime_estimate',
    'perspective', 'alternate_titles',
    'critic_score', 'critic_score_count', 'user_score', 'user_score_count',
    'controller_support', 'save_type', 'campaign', 'other_platforms',
    'edition', 'region', 'game_structure', 'dimension',
]


@pytest.fixture
def blank():
    """Fresh (meta, result) tuple — fixture replaces 30+ inline
    `_blank_metadata()`/`_blank_result()` call pairs (audit MED finding).
    `meta` is a dict of every metadata key set to '', `result` tracks
    filled-field provenance."""
    return ({k: '' for k in _METADATA_KEYS}, {'filled_fields': []})


# ---------------------------------------------------------------------------
# TGDB
# ---------------------------------------------------------------------------

class TestApplyTgdb:
    def test_fills_empty_text_fields(self, blank):
        meta, result = blank
        tgdb = {
            'name': 'Chrono Trigger',
            'publisher': 'Squaresoft',
            'developer': 'Square',
            'release_date': '1995-03-11',
            'summary': 'A time-travel JRPG.',
            'genres': ['Role-Playing'],
            'players': 1,
            'rating': 'ESRB T',
        }
        apply_tgdb_to_metadata(meta, tgdb, db_game_id=42, result=result)
        assert meta['title'] == 'Chrono Trigger'
        assert meta['publisher'] == 'Squaresoft'
        assert meta['developer'] == 'Square'
        assert meta['release_date'] == '1995-03-11'
        assert meta['description'] == 'A time-travel JRPG.'
        assert meta['players'] == 1
        assert meta['esrb_rating'] == 'T'
        # Single-player inferred from players==1
        assert meta['modes'] == 'Single-Player'
        assert any('title (TGDB)' == f for f in result['filled_fields'])

    def test_fill_only_true_preserves_existing_non_title_fields(self, blank):
        meta, result = blank
        meta['publisher'] = 'Pre-existing'
        tgdb = {'name': 'X', 'publisher': 'Replacement'}
        apply_tgdb_to_metadata(meta, tgdb, db_game_id=1, result=result, fill_only=True)
        assert meta['publisher'] == 'Pre-existing'

    def test_fill_only_false_overwrites_title(self, blank):
        meta, result = blank
        meta['title'] = 'Stale'
        apply_tgdb_to_metadata(meta, {'name': 'Fresh'}, db_game_id=1, result=result, fill_only=False)
        assert meta['title'] == 'Fresh'

    def test_fill_only_true_keeps_existing_title(self, blank):
        meta, result = blank
        meta['title'] = 'Original'
        apply_tgdb_to_metadata(meta, {'name': 'Override'}, db_game_id=1, result=result, fill_only=True)
        assert meta['title'] == 'Original'

    def test_players_greater_than_one_sets_multiplayer_mode(self, blank):
        meta, result = blank
        apply_tgdb_to_metadata(meta, {'players': 4}, db_game_id=1, result=result)
        assert meta['players'] == 4
        assert meta['modes'] == 'Single-Player, Multiplayer'

    def test_pegi_parsed_from_rating(self, blank):
        meta, result = blank
        apply_tgdb_to_metadata(meta, {'rating': 'PEGI 16'}, db_game_id=1, result=result)
        assert meta['pegi_rating'] == 'PEGI 16'


# ---------------------------------------------------------------------------
# IGDB
# ---------------------------------------------------------------------------

class TestApplyIgdb:
    def test_fills_empty_text_fields_including_company_mapping(self, blank):
        meta, result = blank
        igdb = {
            'name': 'Halo: Combat Evolved',
            'involved_companies': [
                {'company': {'name': 'Microsoft'}, 'publisher': True, 'developer': False},
                {'company': {'name': 'Bungie'}, 'publisher': False, 'developer': True},
            ],
            'genres': [{'name': 'Shooter'}],
            'summary': 'Master Chief saves the galaxy.',
            'game_modes': [{'name': 'Single player'}, {'name': 'Multiplayer'}],
            'multiplayer_modes': [{'offlinemax': 4}],
        }
        apply_igdb_to_metadata(meta, igdb, db_game_id=1, result=result)
        assert meta['title'] == 'Halo: Combat Evolved'
        assert meta['publisher'] == 'Microsoft'
        assert meta['developer'] == 'Bungie'
        assert meta['description'] == 'Master Chief saves the galaxy.'
        assert meta['players'] == 4

    def test_storyline_preferred_over_summary_for_description(self, blank):
        meta, result = blank
        igdb = {'storyline': 'Long story.', 'summary': 'Short.'}
        apply_igdb_to_metadata(meta, igdb, db_game_id=1, result=result)
        assert meta['description'] == 'Long story.'

    def test_release_date_converted_from_unix_timestamp(self, blank):
        meta, result = blank
        # 2001-11-15 UTC
        apply_igdb_to_metadata(meta, {'first_release_date': 1005782400}, db_game_id=1, result=result)
        assert meta['release_date'] == '2001-11-15'

    def test_age_rating_category_map(self, blank):
        meta, result = blank
        igdb = {
            'age_ratings': [
                {'category': 1, 'rating': 11},  # ESRB M
                {'category': 2, 'rating': 5},   # PEGI 18
                {'category': 3, 'rating': 5},   # CERO Z
                {'category': 4, 'rating': 5},   # USK 18
            ],
        }
        apply_igdb_to_metadata(meta, igdb, db_game_id=1, result=result)
        assert meta['esrb_rating'] == 'M'
        assert meta['pegi_rating'] == 'PEGI 18'
        assert meta['cero_rating'] == 'Z'
        assert meta['usk_rating'] == '18'

    def test_unknown_rating_category_ignored(self, blank):
        meta, result = blank
        # Category 99 doesn't exist in IGDB's schema.
        apply_igdb_to_metadata(meta, {'age_ratings': [{'category': 99, 'rating': 1}]}, db_game_id=1, result=result)
        assert meta['esrb_rating'] == ''
        assert meta['pegi_rating'] == ''

    def test_extended_fields_applied_when_empty(self, blank):
        meta, result = blank
        igdb = {
            '_extended': {
                'franchise': 'Halo',
                'similar_games': 'Destiny, Titanfall',
                'playtime_estimate': 10,
                'perspective': 'First-person',
                'critic_score': 97.5,
                'critic_score_count': 120,
                'user_score': 91.0,
                'user_score_count': 5000,
            },
        }
        apply_igdb_to_metadata(meta, igdb, db_game_id=1, result=result)
        assert meta['franchise'] == 'Halo'
        assert meta['similar_games'] == 'Destiny, Titanfall'
        assert meta['playtime_estimate'] == 10
        assert meta['perspective'] == 'First-person'
        assert meta['critic_score'] == 97.5
        assert meta['critic_score_count'] == 120
        assert meta['user_score'] == 91.0

    def test_alternate_names_merged_with_region(self, blank):
        meta, result = blank
        meta['title'] = 'Mega Man'
        igdb = {
            'alternative_names': [
                {'name': 'Rockman', 'comment': 'Japan'},
                {'name': 'Mega Man', 'comment': 'primary'},  # will be filtered — matches title
            ],
        }
        apply_igdb_to_metadata(meta, igdb, db_game_id=1, result=result)
        assert len(meta['alternate_titles']) == 1
        assert meta['alternate_titles'][0]['title'] == 'Rockman'
        assert meta['alternate_titles'][0]['region'] == 'Japan'
        assert meta['alternate_titles'][0]['source'] == 'igdb'


# ---------------------------------------------------------------------------
# RAWG
# ---------------------------------------------------------------------------

class TestApplyRawg:
    def test_fills_empty_fields_with_fill_only_true(self, blank):
        meta, result = blank
        rawg = {
            'name': 'Portal',
            'description': 'Puzzle with portals.',
            'release_date': '2007-10-10',
            'developer': 'Valve',
            'publisher': 'Valve',
            'genre': 'Puzzle',
            'esrb_rating': 'T',
            'players': 1,
            'modes': 'Single-Player',
            'metacritic': 90,
        }
        apply_rawg_to_metadata(meta, rawg, db_game_id=1, result=result, fill_only=True)
        assert meta['title'] == 'Portal'
        assert meta['description'] == 'Puzzle with portals.'
        assert meta['release_date'] == '2007-10-10'
        assert meta['developer'] == 'Valve'
        assert meta['publisher'] == 'Valve'
        assert meta['esrb_rating'] == 'T'
        assert meta['critic_score'] == 90

    def test_fill_only_false_overwrites_only_title(self, blank):
        # Pass 23.2: only title overwrites on primary source, matching
        # TGDB / IGDB / ScreenScraper. Other fields are always fill-only.
        meta, result = blank
        meta.update({'title': 'Old', 'developer': 'OldDev'})
        rawg = {'name': 'New', 'developer': 'NewDev'}
        apply_rawg_to_metadata(meta, rawg, db_game_id=1, result=result, fill_only=False)
        assert meta['title'] == 'New'
        assert meta['developer'] == 'OldDev'

    def test_release_date_truncated_to_iso(self, blank):
        meta, result = blank
        apply_rawg_to_metadata(meta, {'release_date': '2007-10-10T00:00:00Z'}, db_game_id=1, result=result)
        assert meta['release_date'] == '2007-10-10'

    def test_release_date_too_short_ignored(self, blank):
        meta, result = blank
        apply_rawg_to_metadata(meta, {'release_date': '2007'}, db_game_id=1, result=result)
        assert meta['release_date'] == ''

    def test_franchise_only_fills_empty(self, blank):
        meta, result = blank
        meta['franchise'] = 'Existing'
        # Note: franchise handling in RAWG ignores fill_only and only fills empty.
        apply_rawg_to_metadata(meta, {'franchise': 'Other'}, db_game_id=1, result=result, fill_only=False)
        assert meta['franchise'] == 'Existing'

    def test_franchise_preserved_when_fill_only_true(self, blank):
        """fill_only=True must also leave a populated franchise untouched.
        Earlier test only covered fill_only=False; this pins the invariant
        from the other direction — a refactor that swaps the logic for
        franchise alone would have been invisible."""
        meta, result = blank
        meta['franchise'] = 'Existing'
        apply_rawg_to_metadata(meta, {'franchise': 'Other'}, db_game_id=1, result=result, fill_only=True)
        assert meta['franchise'] == 'Existing'


# ---------------------------------------------------------------------------
# ScreenScraper
# ---------------------------------------------------------------------------

class TestApplyScreenScraper:
    def test_get_localized_region_priority(self, blank):
        meta, result = blank
        ss = {
            'noms': [
                {'region': 'jp', 'text': 'Rockman'},
                {'region': 'us', 'text': 'Mega Man'},
                {'region': 'eu', 'text': 'Mega Man EU'},
            ],
        }
        apply_screenscraper_to_metadata(meta, ss, db_game_id=1, result=result)
        assert meta['title'] == 'Mega Man'

    def test_region_tagged_alt_titles(self, blank):
        meta, result = blank
        ss = {
            'noms': [
                {'region': 'us', 'text': 'Mega Man'},
                {'region': 'jp', 'text': 'Rockman'},
                {'region': 'eu', 'text': 'Mega Man EU'},
            ],
        }
        apply_screenscraper_to_metadata(meta, ss, db_game_id=1, result=result)
        assert meta['title'] == 'Mega Man'
        titles = {e['title'] for e in meta['alternate_titles']}
        # Primary title is excluded from alt titles.
        assert 'Rockman' in titles
        assert 'Mega Man EU' in titles
        assert 'Mega Man' not in titles

    def test_fills_developer_publisher_from_dict_or_str(self, blank):
        meta, result = blank
        ss = {
            'developpeur': {'text': 'Capcom'},
            'editeur': 'Nintendo',
        }
        apply_screenscraper_to_metadata(meta, ss, db_game_id=1, result=result)
        assert meta['developer'] == 'Capcom'
        assert meta['publisher'] == 'Nintendo'

    def test_classifications_map_to_rating_fields(self, blank):
        meta, result = blank
        ss = {
            'classifications': [
                {'type': 'ESRB', 'text': 'T'},
                {'type': 'PEGI', 'text': '12'},
                {'type': 'CERO', 'text': 'B'},
                {'type': 'USK', 'text': '12'},
                {'type': 'ACB', 'text': 'M'},
            ],
        }
        apply_screenscraper_to_metadata(meta, ss, db_game_id=1, result=result)
        assert meta['esrb_rating'] == 'T'
        assert meta['pegi_rating'] == 'PEGI 12'
        assert meta['cero_rating'] == 'B'
        assert meta['usk_rating'] == '12'
        assert meta['acb_rating'] == 'M'

    def test_note_converted_0_20_to_0_100(self, blank):
        meta, result = blank
        # ScreenScraper note is 0-20 scale; 17.0 → 85.0
        apply_screenscraper_to_metadata(meta, {'note': {'text': '17.0'}}, db_game_id=1, result=result)
        assert meta['user_score'] == 85.0

    def test_existing_text_fields_not_overwritten(self, blank):
        meta, result = blank
        meta.update({'description': 'Existing desc', 'developer': 'Existing dev'})
        ss = {
            'synopsis': [{'region': 'us', 'text': 'New desc'}],
            'developpeur': 'New dev',
        }
        apply_screenscraper_to_metadata(meta, ss, db_game_id=1, result=result)
        assert meta['description'] == 'Existing desc'
        assert meta['developer'] == 'Existing dev'


# ---------------------------------------------------------------------------
# AI
# ---------------------------------------------------------------------------

class TestApplyAi:
    def test_none_data_is_noop(self, blank):
        meta, result = blank
        meta['title'] = 'Keep me'
        apply_ai_to_metadata(meta, None, db_game_id=1, result=result)
        assert meta['title'] == 'Keep me'
        assert result['filled_fields'] == []

    def test_fills_simple_text_fields_when_empty(self, blank):
        meta, result = blank
        ai = {
            'description': 'Auto desc.',
            'developer': 'DevCo',
            'publisher': 'PubCo',
            'players': 2,
            'region': 'World',
            'franchise': 'MyFranchise',
        }
        apply_ai_to_metadata(meta, ai, db_game_id=1, result=result)
        assert meta['description'] == 'Auto desc.'
        assert meta['developer'] == 'DevCo'
        assert meta['publisher'] == 'PubCo'
        assert meta['players'] == 2
        assert meta['region'] == 'World'
        assert meta['franchise'] == 'MyFranchise'

    def test_fill_only_true_preserves_existing_non_validate_fields(self, blank):
        meta, result = blank
        meta['description'] = 'Original desc'
        apply_ai_to_metadata(meta, {'description': 'AI override'}, db_game_id=1, result=result, fill_only=True)
        assert meta['description'] == 'Original desc'

    def test_apply_ai_fill_only_false_overwrites_existing_fields(self, blank):
        """fill_only=False is the overwrite path — pre-existing values get
        replaced. Mirrors the TGDB `test_fill_only_false_overwrites_title`
        for the AI source so a regression that silently flips the default
        back to fill-only would fail loudly."""
        meta, result = blank
        meta['description'] = 'Original desc'
        meta['publisher'] = 'Original pub'
        apply_ai_to_metadata(
            meta,
            {'description': 'AI override', 'publisher': 'AI pub'},
            db_game_id=1,
            result=result,
            fill_only=False,
        )
        assert meta['description'] == 'AI override'
        assert meta['publisher'] == 'AI pub'

    def test_validate_fields_always_applied_even_when_fill_only(self, blank):
        # VALIDATE_FIELDS (from scrape_ai) always override — AI is treated as
        # a correction source for those. Sanity-check with a known entry.
        from scraper.scrape_ai import VALIDATE_FIELDS
        if not VALIDATE_FIELDS:
            pytest.skip("VALIDATE_FIELDS empty on this build")
        field = next(iter(VALIDATE_FIELDS))
        if field not in _METADATA_KEYS:
            pytest.skip(f"VALIDATE_FIELDS entry {field} not in test metadata skeleton")
        meta, result = blank
        meta[field] = 'stale'
        apply_ai_to_metadata(meta, {field: 'corrected'}, db_game_id=1, result=result, fill_only=True)
        assert meta[field] == 'corrected'

    def test_scores_coerced_to_int(self, blank):
        meta, result = blank
        ai = {'critic_score': '87.6', 'user_score': 92}
        apply_ai_to_metadata(meta, ai, db_game_id=1, result=result)
        assert meta['critic_score'] == 87
        assert meta['user_score'] == 92

    def test_non_numeric_score_silently_dropped(self, blank):
        meta, result = blank
        apply_ai_to_metadata(meta, {'critic_score': 'not a number'}, db_game_id=1, result=result)
        assert meta['critic_score'] == ''
