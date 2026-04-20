"""
Regression tests for the pure helpers in services/game_utils.py.

These lock down the functions that caused or could have caused bugs in the
past (F601 duplicate-key maps, article placement, rating cross-mapping) so
future refactors don't silently change behaviour.
"""

from services.game_utils import (
    move_article_to_beginning,
    move_article_to_end,
    normalize_article_for_comparison,
    PLATFORM_NAME_MAP,
    _sanitize_filename_value,
)


# -- Article placement -------------------------------------------------------

class TestArticleMovement:
    def test_leading_the_moves_to_end(self):
        assert move_article_to_end("The Legend of Zelda") == "Legend of Zelda, The"

    def test_leading_a_moves_to_end(self):
        assert move_article_to_end("A Bug's Life") == "Bug's Life, A"

    def test_leading_an_moves_to_end(self):
        assert move_article_to_end("An American Tail") == "American Tail, An"

    def test_no_article_passthrough(self):
        assert move_article_to_end("Metal Gear Solid") == "Metal Gear Solid"

    def test_trailing_the_moves_to_beginning(self):
        assert move_article_to_beginning("Legend of Zelda, The") == "The Legend of Zelda"

    def test_trailing_article_is_case_insensitive(self):
        assert move_article_to_beginning("Legend of Zelda, the") == "the Legend of Zelda"

    def test_abbreviation_not_treated_as_article(self):
        # The regex uses negative lookahead for '.' or '-' so "A.L.F." / "A-Team" stay put.
        assert move_article_to_end("A.L.F.") == "A.L.F."
        assert move_article_to_end("A-Team") == "A-Team"

    def test_empty_string_returns_empty(self):
        assert move_article_to_end("") == ""
        assert move_article_to_beginning("") == ""

    def test_none_returns_none(self):
        assert move_article_to_end(None) is None
        assert move_article_to_beginning(None) is None

    def test_normalize_for_comparison_always_beginning(self):
        # Both forms should compare equal after normalization.
        a = normalize_article_for_comparison("The Legend of Zelda")
        b = normalize_article_for_comparison("Legend of Zelda, The")
        assert a == b == "The Legend of Zelda"


# -- PLATFORM_NAME_MAP (regression for F601 duplicate-key bug) ---------------

class TestPlatformNameMap:
    def test_sega_cd_maps_to_sega_cd(self):
        assert PLATFORM_NAME_MAP["sega cd"] == "Sega CD"

    def test_segacd_compact_form_maps_to_sega_cd(self):
        assert PLATFORM_NAME_MAP["segacd"] == "Sega CD"

    def test_mega_cd_maps_to_mega_cd(self):
        assert PLATFORM_NAME_MAP["mega cd"] == "Mega CD"

    def test_megacd_compact_form_maps_to_mega_cd(self):
        assert PLATFORM_NAME_MAP["megacd"] == "Mega CD"

    def test_no_duplicate_keys_in_map(self):
        # If the literal dict has duplicate keys, Python silently keeps the last
        # value — a past F601 finding let two 'sega cd' entries slip in. This
        # test would not catch that (dict already deduped), so instead we
        # parse the source and assert no line-level repeats.
        import services.game_utils as gu
        import inspect
        source = inspect.getsource(gu)
        # Extract the PLATFORM_NAME_MAP block
        start = source.index("PLATFORM_NAME_MAP = {")
        end = source.index("\n}\n", start)
        block = source[start:end]
        # Pull all 'key' literals
        import re
        keys = re.findall(r"^\s*'([^']+)'\s*:", block, re.MULTILINE)
        duplicates = {k for k in keys if keys.count(k) > 1}
        assert not duplicates, f"Duplicate keys in PLATFORM_NAME_MAP: {sorted(duplicates)}"


# -- Filename sanitization ---------------------------------------------------

class TestFilenameSanitization:
    def test_strips_colons(self):
        assert _sanitize_filename_value("Sonic: The Hedgehog") == "Sonic - The Hedgehog"

    def test_strips_slashes(self):
        assert _sanitize_filename_value("Rock/Paper") == "Rock-Paper"

    def test_strips_question_mark(self):
        assert _sanitize_filename_value("Where in the World?") == "Where in the World"

    def test_handles_empty(self):
        assert _sanitize_filename_value("") == ""
        assert _sanitize_filename_value(None) == ""

    def test_trims_whitespace(self):
        assert _sanitize_filename_value("  Metroid Prime  ") == "Metroid Prime"
