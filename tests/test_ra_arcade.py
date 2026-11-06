"""Arcade is back in RetroAchievements (user, 2026-11-06). RetroAchievements
knows an arcade game by the MD5 of its file name without the extension, case
and all (docs.retroachievements.org, game identification, Arcade). Checked
against its Arcade list on 2026-11-06: `galaga`, `sf2` and `pacman` hit.
A title never links an arcade game: that was the over-matching it was left
out for."""
import hashlib

import pytest

from services.achievement_linking import match_ra_game_for_file
from services.game_utils import ARCADE_SET_FOLDERS

SF2 = {'ID': 1, 'Title': 'Street Fighter II: The World Warrior', 'NumAchievements': 40,
       'Hashes': [hashlib.md5(b'sf2').hexdigest()]}
D = {'ID': 2, 'Title': 'D', 'NumAchievements': 5, 'Hashes': ['0' * 32]}


@pytest.mark.parametrize('folder', ARCADE_SET_FOLDERS)
def test_every_arcade_folder_is_an_ra_console(folder):
    from scraper.retroachievements import get_ra_console_id
    assert get_ra_console_id(folder) == 27


def test_an_arcade_set_is_known_by_its_file_name():
    match, fits = match_ra_game_for_file('Street Fighter II (World 910522)',
                                         '/roms/mame/sf2.zip', 'mame', [SF2, D])
    assert match is SF2 and fits == 1


def test_the_file_name_keeps_its_case():
    assert match_ra_game_for_file('Street Fighter II', '/roms/mame/SF2.zip',
                                  'mame', [SF2]) == (None, None)


def test_a_title_never_links_an_arcade_game():
    assert match_ra_game_for_file('D', '/roms/mame/dyger.zip', 'mame', [SF2, D]) == (None, None)
    assert match_ra_game_for_file('Street Fighter II: The World Warrior', '',
                                  'fbneo', [SF2]) == (None, None)
