"""The game page's RetroAchievements card comes from the RA link the game
already has (the one the Library's RA badge shows), not a fresh title search
that can miss it (GameCube: Metroid Prime, Metroid Prime 2)."""
from unittest.mock import patch

from services.game_query import get_retroachievements_info


def test_stored_link_is_used_without_asking_ra():
    game = {'title': 'Metroid Prime 2 (USA)', 'ra_game_id': 3711,
            'ra_achievement_count': 54, 'ra_points': 610}
    with patch('scraper.retroachievements.check_retroachievements') as search, \
         patch('scraper.retroachievements.get_game_info') as by_id:
        info = get_retroachievements_info(game)
    search.assert_not_called()
    by_id.assert_not_called()
    assert info == {'id': 3711, 'achievement_count': 54, 'points': 610,
                    'has_achievements': True,
                    'url': 'https://retroachievements.org/game/3711'}


def test_link_without_a_count_is_looked_up_by_id():
    game = {'ra_game_id': 3711, 'ra_achievement_count': None}
    found = {'id': 3711, 'achievement_count': 54, 'has_achievements': True,
             'url': 'https://retroachievements.org/game/3711'}
    with patch('scraper.retroachievements.get_game_info', return_value=found) as by_id:
        assert get_retroachievements_info(game) == found
    by_id.assert_called_once_with(3711)


def test_unlinked_game_has_no_card():
    with patch('scraper.retroachievements.check_retroachievements') as search:
        assert get_retroachievements_info({'title': 'Metroid Prime', 'ra_game_id': None}) is None
    search.assert_not_called()


def test_game_page_shows_the_card_from_the_stored_link(admin_test_client):
    import os
    import sqlite3
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT INTO systems (name, folder) VALUES ('Nintendo GameCube', 'ra_card_gc')")
    sid = conn.execute("SELECT id FROM systems WHERE folder = 'ra_card_gc'").fetchone()[0]
    gid = conn.execute(
        "INSERT INTO games (system_id, title, rom_path, has_retroachievements, ra_game_id, "
        "ra_achievement_count, ra_points) VALUES (?, 'Metroid Prime', '/roms/mp.iso', 1, 3700, 61, 700)",
        (sid,)).lastrowid
    conn.commit()
    try:
        client, _ = admin_test_client()
        with patch('scraper.retroachievements.check_retroachievements', return_value=None):
            html = client.get(f'/game/{gid}').get_data(as_text=True)
        assert 'achievement-item ra' in html
        assert 'https://retroachievements.org/game/3700' in html
    finally:
        conn.execute("DELETE FROM games WHERE system_id = ?", (sid,))
        conn.execute("DELETE FROM systems WHERE id = ?", (sid,))
        conn.commit()
        conn.close()
