# =============================================================================
# Pass 38.1 (partial) — _normalize_players_and_sort_title helper
# =============================================================================
# The NORMALIZE VALUES block of apply_hybrid_metadata had two small inline
# normalizations: reduce a players range/prose to the max integer (the DB
# column is INTEGER), and regenerate sort_title from the (possibly newly
# filled) title. Pass 38.1 (partial) extracted both into a helper so the
# apply_hybrid_metadata tail is shorter and the contract is testable in
# isolation. These tests pin:
#   - "1-4" / "1-2" → max integer (4 / 2)
#   - prose "2 players" → 2 (max digit run)
#   - no-digit string ("Single") → None (cleared)
#   - "" / None / missing key → left untouched (falsy guard)
#   - sort_title regenerated to match generate_sort_title(title)
#   - no title → sort_title key never added
# =============================================================================

from tests._util import REPO_ROOT  # noqa: F401  (ensures sys.path is set)


class TestNormalizePlayersAndSortTitle:
    def test_range_reduces_to_max(self):
        from scraper import hybrid_scraper

        metadata = {'players': '1-4', 'title': None}
        hybrid_scraper._normalize_players_and_sort_title(metadata)
        assert metadata['players'] == 4

    def test_two_player_range(self):
        from scraper import hybrid_scraper

        metadata = {'players': '1-2', 'title': None}
        hybrid_scraper._normalize_players_and_sort_title(metadata)
        assert metadata['players'] == 2

    def test_prose_with_digits_picks_max_run(self):
        from scraper import hybrid_scraper

        metadata = {'players': '2 players', 'title': None}
        hybrid_scraper._normalize_players_and_sort_title(metadata)
        assert metadata['players'] == 2

    def test_no_digit_string_cleared_to_none(self):
        from scraper import hybrid_scraper

        metadata = {'players': 'Single', 'title': None}
        hybrid_scraper._normalize_players_and_sort_title(metadata)
        assert metadata['players'] is None

    def test_empty_string_left_untouched(self):
        """Falsy guard: '' never enters the digit-extract branch."""
        from scraper import hybrid_scraper

        metadata = {'players': '', 'title': None}
        hybrid_scraper._normalize_players_and_sort_title(metadata)
        assert metadata['players'] == ''

    def test_none_players_left_untouched(self):
        from scraper import hybrid_scraper

        metadata = {'players': None, 'title': None}
        hybrid_scraper._normalize_players_and_sort_title(metadata)
        assert metadata['players'] is None

    def test_already_integer_preserved(self):
        from scraper import hybrid_scraper

        metadata = {'players': 4, 'title': None}
        hybrid_scraper._normalize_players_and_sort_title(metadata)
        assert metadata['players'] == 4

    def test_sort_title_regenerated_from_title(self):
        from scraper import hybrid_scraper
        from services.game_utils import generate_sort_title

        metadata = {'players': None, 'title': 'The Legend of Zelda'}
        hybrid_scraper._normalize_players_and_sort_title(metadata)
        # Helper must defer to the canonical generator, not roll its own.
        assert metadata['sort_title'] == generate_sort_title('The Legend of Zelda')

    def test_no_title_does_not_add_sort_title(self):
        from scraper import hybrid_scraper

        metadata = {'players': None, 'title': None}
        hybrid_scraper._normalize_players_and_sort_title(metadata)
        assert 'sort_title' not in metadata
