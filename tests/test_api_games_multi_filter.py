"""PASS-53-11 — a Library filter takes several values: a game matches if it
has any of them, and an exclude hides a game that has any of them. Values
arrive as repeated query params (?genre=A&genre=B), since a value may
itself contain a comma."""
import pytest

from tests._versions_util import vdb  # noqa: F401 — fixture


@pytest.fixture
def games(vdb):
    d = vdb
    d.game('Alpha', genre='Action')
    d.game('Bravo', genre='RPG')
    d.game('Charlie', genre='Puzzle')
    d.game('Delta', genre='Action, RPG', publisher='Acme, Inc.')
    d.game('Echo', publisher='Other')
    return d


def _titles(admin_test_client, path):
    client, _ = admin_test_client(settings={'setup_completed': True})
    resp = client.get(path)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return [g['title'] for g in resp.get_json()['games']]


def test_two_values_match_either(games, admin_test_client):
    assert _titles(admin_test_client,
                   f'/api/games?system={games.sid}&genre=Action&genre=Puzzle') \
        == ['Alpha', 'Charlie', 'Delta']


def test_one_value_still_works(games, admin_test_client):
    assert _titles(admin_test_client, f'/api/games?system={games.sid}&genre=RPG') \
        == ['Bravo', 'Delta']


def test_two_excludes_hide_either(games, admin_test_client):
    assert _titles(admin_test_client,
                   f'/api/games?system={games.sid}&not_genre=Action&not_genre=RPG') \
        == ['Charlie', 'Echo']


def test_value_with_a_comma_is_one_value(games, admin_test_client):
    assert _titles(admin_test_client,
                   f'/api/games?system={games.sid}&publisher=Acme%2C+Inc.') \
        == ['Delta']


def test_select_all_ids_honour_every_value(games, admin_test_client):
    client, _ = admin_test_client(settings={'setup_completed': True})
    resp = client.get(f'/api/games/ids?system={games.sid}&genre=Action&genre=Puzzle')
    assert resp.status_code == 200
    assert len(resp.get_json()['ids']) == 3
