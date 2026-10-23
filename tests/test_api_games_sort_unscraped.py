"""PASS-53-2 — /api/games honours the Library's sort control and its
Unscraped filter, which the Library and system pages both read."""
import pytest

from tests._versions_util import vdb  # noqa: F401 — fixture


@pytest.fixture
def games(vdb):
    d = vdb
    ids = {
        'low': d.game('Alpha', scraped=1, critic_score=50),
        'high': d.game('Bravo', scraped=0, critic_score=90),
        'none': d.game('Charlie', scraped=0),
    }
    return d, ids


def _titles(admin_test_client, path):
    client, _ = admin_test_client(settings={'setup_completed': True})
    resp = client.get(path)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return [g['title'] for g in resp.get_json()['games']]


def test_sort_reaches_the_query(games, admin_test_client):
    d, _ = games
    assert _titles(admin_test_client, f'/api/games?system={d.sid}&sort=critic_score') \
        == ['Bravo', 'Alpha', 'Charlie']


def test_unscraped_shows_only_unscraped(games, admin_test_client):
    d, _ = games
    assert _titles(admin_test_client, f'/api/games?system={d.sid}&unscraped=1') \
        == ['Bravo', 'Charlie']


def test_without_unscraped_shows_all(games, admin_test_client):
    d, _ = games
    assert _titles(admin_test_client, f'/api/games?system={d.sid}') \
        == ['Alpha', 'Bravo', 'Charlie']
