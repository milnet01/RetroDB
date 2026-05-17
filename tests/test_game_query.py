# Tests for services/game_query.py — the shared game-list query helpers.

import pytest

from services.game_query import escape_like, _build_games_query


class TestEscapeLike:
    def test_plain_string_unchanged(self):
        assert escape_like("zelda") == "zelda"

    def test_percent_escaped(self):
        # % in user input must not become a SQL wildcard
        assert escape_like("100%") == "100\\%"

    def test_underscore_escaped(self):
        # _ in user input must not become a single-char wildcard
        assert escape_like("final_fantasy") == "final\\_fantasy"

    def test_backslash_escaped_first(self):
        # Backslash must be doubled BEFORE % and _ are escaped so that the
        # escape markers we introduce are themselves not literalised again.
        assert escape_like("a\\b") == "a\\\\b"

    def test_combined(self):
        assert escape_like("50%_off\\") == "50\\%\\_off\\\\"

    def test_empty_string(self):
        assert escape_like("") == ""


class TestBuildGamesQuery:
    def test_show_bonus_true_produces_no_filter(self):
        # With show_bonus=1 and no other params, the fallback WHERE 1=1 kicks in
        sql, vals = _build_games_query({'show_bonus': '1'})
        assert "WHERE 1=1" in sql
        assert vals == []

    def test_empty_params_hides_bonus_discs_by_default(self):
        # Default behaviour: hide bonus discs (show_bonus defaults to '0').
        sql, vals = _build_games_query({})
        assert "is_bonus_disc = 0" in sql

    def test_show_bonus_removes_filter(self):
        sql, vals = _build_games_query({'show_bonus': '1'})
        # With show_bonus=1 no bonus-disc condition is added
        assert "is_bonus_disc = 0" not in sql

    def test_system_filter(self):
        sql, vals = _build_games_query({'system': '42'})
        assert "g.system_id = ?" in sql
        # The SUT passes params['system'] verbatim — value comes off the query
        # string as a str. Pin the actual type so a future int-coercion in the
        # SUT shows up here (was: `42 in vals or '42' in vals`, ambiguous).
        assert '42' in vals

    def test_search_filter_escapes_wildcards(self):
        sql, vals = _build_games_query({'search': '100%'})
        # Both title and sort_title should have LIKE conditions
        assert "g.title LIKE ?" in sql
        # User's % must be escaped to \% in the bind value
        assert any('100\\%' in str(v) for v in vals)

    def test_letter_hash_matches_non_alpha(self):
        sql, vals = _build_games_query({'letter': '#'})
        assert "NOT BETWEEN 'A' AND 'Z'" in sql

    def test_letter_alpha_binds_upper(self):
        sql, vals = _build_games_query({'letter': 'z'})
        # The SUT does `values.append(letter.upper())` — the bound value
        # must be the literal string 'Z'. Was: substring on str(vals), which
        # would also pass for vals containing 'ZERO' or any 'Z*' string.
        assert 'Z' in vals

    def test_ra_only_filter(self):
        sql, vals = _build_games_query({'ra_only': '1'})
        assert "has_retroachievements = 1" in sql

    def test_count_only_emits_count_query(self):
        sql, vals = _build_games_query({}, count_only=True)
        assert "SELECT COUNT(*)" in sql
        assert "ORDER BY" not in sql  # counts don't need ordering

    def test_ids_only_emits_id_column(self):
        sql, vals = _build_games_query({}, ids_only=True)
        assert "SELECT g.id FROM" in sql
        assert "ORDER BY COALESCE(g.sort_title" in sql

    def test_data_query_includes_expected_columns(self):
        sql, vals = _build_games_query({})
        # Spot-check a few columns that must not disappear
        for col in ['g.title', 'g.boxart', 'g.critic_score', 's.name AS system_name',
                    'bc.bonus_count', 'gap.earned_achievements']:
            assert col in sql, f"missing column {col} in SELECT"

    def test_not_filters_include_null_safe(self):
        sql, vals = _build_games_query({'not_genre': 'Horror'})
        # NOT filters must include `OR IS NULL` so null-genre rows aren't
        # accidentally excluded (they don't contain Horror either).
        assert "g.genre IS NULL" in sql

    def test_source_clz(self):
        sql, _ = _build_games_query({'source': 'clz'})
        assert "g.rom_path LIKE 'clz_import/%'" in sql

    def test_source_steam(self):
        sql, _ = _build_games_query({'source': 'steam'})
        assert "g.rom_path LIKE 'steam_import/%'" in sql

    def test_source_rom_excludes_all_imports(self):
        sql, _ = _build_games_query({'source': 'rom'})
        for marker in ['clz_import', 'steam_import', 'xbox_import', 'psn_import']:
            assert marker in sql

    def test_rating_filter_ORs_all_rating_systems(self):
        sql, vals = _build_games_query({'rating': 'T'})
        # rating searches across every rating-system column
        assert 'esrb_rating' in sql
        assert 'pegi_rating' in sql
        # Should bind 'T' once per rating system
        assert vals.count('T') >= 8

    @pytest.mark.parametrize("field", ['genre', 'franchise', 'developer', 'publisher', 'modes', 'perspective', 'dimension'])
    def test_multivalue_fields_use_like_with_escape(self, field):
        sql, vals = _build_games_query({field: 'Value'})
        # SQL literal: ESCAPE '\' (single backslash — the LIKE escape char).
        assert f"g.{field} LIKE ? ESCAPE '\\'" in sql
        assert '%Value%' in vals
