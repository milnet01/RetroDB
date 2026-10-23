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
        # With show_bonus=1 and no other params, the fallback WHERE 1=1 kicks in.
        # group_versions=False: these tests pin the filters; the PASS-59-106
        # grouping wrapper is pinned by tests/test_version_groups_query.py.
        sql, vals = _build_games_query({'show_bonus': '1'}, group_versions=False)
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
        sql, vals = _build_games_query({'system': '42'}, group_versions=False)
        assert "g.system_id = ?" in sql
        # The SUT passes params['system'] verbatim — value comes off the query
        # string as a str. Pin the exact bound-value list so a future
        # int-coercion (or an extra append elsewhere) shows up here. The
        # earlier `'42' in vals` form would have passed for any vals list
        # that contained '42' anywhere, including as a LIKE pattern fragment.
        assert vals == ['42']

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
        # must be the literal string 'Z'. `'Z' in vals` alone would pass
        # for a vals list with 'ZERO' or duplicate 'Z' entries; pin the
        # count to 1 so a stray extra append elsewhere lights this up.
        assert 'Z' in vals and vals.count('Z') == 1

    def test_ra_only_filter(self):
        sql, vals = _build_games_query({'ra_only': '1'})
        assert "has_retroachievements = 1" in sql

    def test_count_only_emits_count_query(self):
        sql, vals = _build_games_query({}, count_only=True, group_versions=False)
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


class TestSortOrder:
    """PASS-53-2 — the Library sort control. Runs the real SQL so the
    order (missing values last, ties broken by name) is what is pinned,
    not the text of the ORDER BY."""

    @pytest.fixture
    def db(self):
        import sqlite3
        conn = sqlite3.connect(':memory:')
        conn.executescript("""
            CREATE TABLE systems (id INTEGER PRIMARY KEY, system_type TEXT);
            CREATE TABLE games (id INTEGER PRIMARY KEY, system_id INTEGER,
                title TEXT, sort_title TEXT, is_bonus_disc INTEGER DEFAULT 0,
                release_date TEXT, critic_score REAL, user_score REAL,
                created_at TEXT);
            INSERT INTO systems VALUES (1, 'Console');
            INSERT INTO games (id, system_id, title, release_date, critic_score, user_score, created_at) VALUES
                (1, 1, 'Bravo',   '1994-05-01', 70,   NULL, '2026-01-03'),
                (2, 1, 'alpha',   '',           NULL, 90,   '2026-01-01'),
                (3, 1, 'Charlie', '1991',       95,   60,   '2026-01-02'),
                (4, 1, 'Delta',   NULL,         70,   60,   NULL);
        """)
        yield conn
        conn.close()

    def _ids(self, db, sort):
        params = {'sort': sort} if sort is not None else {}
        sql, vals = _build_games_query(params, ids_only=True, group_versions=False)
        return [r[0] for r in db.execute(sql, vals)]

    @pytest.mark.parametrize("sort, expected", [
        (None,           [2, 1, 3, 4]),   # name, case-insensitive
        ('name',         [2, 1, 3, 4]),
        ('release_new',  [1, 3, 2, 4]),   # blank and NULL dates last
        ('release_old',  [3, 1, 2, 4]),
        ('critic_score', [3, 1, 4, 2]),   # tie at 70 broken by name
        ('user_score',   [2, 3, 4, 1]),
        ('added',        [1, 3, 2, 4]),   # newest first, no date last
        ('bogus',        [2, 1, 3, 4]),   # unknown falls back to name
        ('',             [2, 1, 3, 4]),
    ])
    def test_sort(self, db, sort, expected):
        assert self._ids(db, sort) == expected

    def test_data_query_uses_same_sort(self):
        sql, _ = _build_games_query({'sort': 'critic_score'}, group_versions=False)
        assert "g.critic_score DESC" in sql
