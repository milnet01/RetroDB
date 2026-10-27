"""Previous / Next on the game page — /api/games/neighbors steps through the
list the game was opened from, under that list's filters and sort."""
import pytest

from services import version_groups as vg
from tests._versions_util import vdb  # noqa: F401 — fixture


@pytest.fixture
def games(vdb):
    ids = {
        'alpha': vdb.game('Alpha', critic_score=50, scraped=1),
        'bravo': vdb.game('Bravo', critic_score=90, scraped=0),
        'charlie': vdb.game('Charlie', scraped=0),
    }
    return vdb, ids


def _get(admin_test_client, qs):
    client, _ = admin_test_client(settings={
        'setup_completed': True, 'default_region': 'USA',
        'region_options': ['USA', 'Japan']})
    resp = client.get(f'/api/games/neighbors?{qs}')
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return resp.get_json()


def test_middle_game_has_both_neighbours(games, admin_test_client):
    d, ids = games
    data = _get(admin_test_client, f"id={ids['bravo']}&system={d.sid}")
    assert data['found'] is True
    assert (data['position'], data['total']) == (2, 3)
    assert data['prev'] == {'id': ids['alpha'], 'title': 'Alpha'}
    assert data['next'] == {'id': ids['charlie'], 'title': 'Charlie'}


def test_ends_have_one_neighbour(games, admin_test_client):
    d, ids = games
    first = _get(admin_test_client, f"id={ids['alpha']}&system={d.sid}")
    last = _get(admin_test_client, f"id={ids['charlie']}&system={d.sid}")
    assert first['prev'] is None and first['next']['id'] == ids['bravo']
    assert last['next'] is None and last['prev']['id'] == ids['bravo']


def test_follows_the_lists_sort(games, admin_test_client):
    d, ids = games
    data = _get(admin_test_client, f"id={ids['alpha']}&system={d.sid}&sort=critic_score")
    # Bravo (90), Alpha (50), Charlie (no score)
    assert data['prev']['id'] == ids['bravo']
    assert data['next']['id'] == ids['charlie']


def test_follows_the_lists_filters(games, admin_test_client):
    d, ids = games
    data = _get(admin_test_client, f"id={ids['charlie']}&system={d.sid}&unscraped=1")
    assert data['total'] == 2
    assert data['prev']['id'] == ids['bravo'] and data['next'] is None


def test_game_outside_the_filters_is_not_found(games, admin_test_client):
    d, ids = games
    data = _get(admin_test_client, f"id={ids['alpha']}&system={d.sid}&unscraped=1")
    assert data['found'] is False


def test_folded_version_is_placed_at_its_card(vdb, admin_test_client):
    before = vdb.game('Aardvark')
    us = vdb.game('Mega Man', rom='Mega Man (USA).zip')
    jp = vdb.game('Rockman', rom='Rockman (Japan).zip', region='Japan')
    after = vdb.game('Zebra')
    vg.link([us, jp])
    data = _get(admin_test_client, f"id={jp}&system={vdb.sid}")
    assert data['found'] is True
    assert data['prev']['id'] == before and data['next']['id'] == after


def test_missing_id_is_rejected(admin_test_client):
    client, _ = admin_test_client()
    resp = client.get('/api/games/neighbors')
    assert resp.get_json()['success'] is False
