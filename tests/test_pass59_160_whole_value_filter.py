"""PASS-59-160: a filter on a comma-separated field matches whole values.

"Action" used to match "Action-Adventure" too, so the Library's filter
returned more games than the filter window's count said. The same match
fed a game page's tag lists and its Similar games.
"""
import pytest

from tests._versions_util import vdb  # noqa: F401 — fixture


@pytest.fixture
def games(vdb):
    d = vdb
    d.ids = {
        'Hero': d.game('Hero', genre='Action', developer='Dev160', franchise='Saga160'),
        'Pair': d.game('Pair', genre='RPG,Action', developer='Dev160', franchise='Saga160'),
        'Near': d.game('Near', genre='Action-Adventure', developer='Dev160',
                       franchise='Saga160 Kart'),
        'Other': d.game('Other', genre='Puzzle'),
    }
    return d


def _client(admin_test_client):
    client, _ = admin_test_client(settings={'setup_completed': True})
    return client


def _titles(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return sorted(g['title'] for g in resp.get_json()['games'])


def test_library_filter_matches_whole_values(games, admin_test_client):
    client = _client(admin_test_client)
    assert _titles(client, f'/api/games?system={games.sid}&genre=Action') == ['Hero', 'Pair']


def test_library_exclude_matches_whole_values(games, admin_test_client):
    client = _client(admin_test_client)
    assert _titles(client, f'/api/games?system={games.sid}&not_genre=Action') \
        == ['Near', 'Other']


def test_tag_list_matches_whole_values(games, admin_test_client):
    client = _client(admin_test_client)
    assert _titles(client, '/api/filter-games?type=franchise&value=Saga160') == ['Hero', 'Pair']


def test_similar_games_match_whole_values(games, admin_test_client):
    client = _client(admin_test_client)
    found = _titles(client, f"/api/games/{games.ids['Hero']}/similar")
    assert 'Pair' in found and 'Near' not in found
