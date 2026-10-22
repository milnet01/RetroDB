"""The players field takes any count a game supports.

Both edit forms capped players at 16, so a game scraped with 64 could not be
saved at all, and MAG (PS3, 256 players) could not be entered. The server has
no upper cap; the forms must not add one.
"""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.parametrize('template, input_id', [
    ('templates/_modals/edit_modal.html', 'edit_players'),
    ('templates/base.html', 'gemPlayers'),
])
def test_players_input_has_no_upper_cap(template, input_id):
    src = (ROOT / template).read_text(encoding='utf-8')
    tag = re.search(r'<input[^>]*id="' + input_id + r'"[^>]*>', src).group(0)
    assert 'min="1"' in tag
    assert 'max=' not in tag


def test_server_keeps_large_player_counts():
    from services.game_utils import normalize_players_value
    assert normalize_players_value('256') == 256
