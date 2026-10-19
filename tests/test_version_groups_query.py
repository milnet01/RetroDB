"""PASS-59-106 INV-4, INV-5, INV-6 — the Library shows one card per group.

docs/specs/PASS-59-106-regional-versions.md §4.2, §4.3 and §5. Driven through
/api/games and /api/games/ids, which the Library and system pages both read.
"""
import pytest

from services import version_groups as vg
from tests._versions_util import vdb  # noqa: F401 — fixture

REGIONS = ['USA', 'Europe', 'Japan', 'World']


@pytest.fixture
def group(vdb):
    # Inserted Japan first, so "lowest id wins" never passes by accident.
    jp = vdb.game('Rockman', rom='Rockman (Japan).zip', region='Japan')
    world = vdb.game('Mega Man', rom='Mega Man (World).zip', region='')
    us = vdb.game('Mega Man', rom='Mega Man (USA, Europe).zip', region='')
    vg.link([jp, world, us])
    return vdb, {'jp': jp, 'world': world, 'us': us}


def _get(admin_test_client, default_region, path):
    client, _ = admin_test_client(settings={
        'setup_completed': True, 'default_region': default_region,
        'region_options': REGIONS})
    resp = client.get(path)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return resp.get_json()


# INV-4 — one row, the preferred version by rank, counting the whole group.
@pytest.mark.parametrize('default_region,expected', [
    ('USA', 'us'), ('Japan', 'jp'), ('Germany', 'world')])
def test_inv4_one_card_shows_preferred_version(group, admin_test_client,
                                               default_region, expected):
    d, ids = group
    data = _get(admin_test_client, default_region, f'/api/games?system={d.sid}')
    assert [g['id'] for g in data['games']] == [ids[expected]]
    assert data['games'][0]['version_count'] == 3
    assert data['games'][0]['version_group_id'] == d.group_of(ids[expected])


# INV-5 — filters run before grouping.
def test_inv5_search_finds_the_matching_version(group, admin_test_client):
    d, ids = group
    data = _get(admin_test_client, 'USA', f'/api/games?system={d.sid}&search=Rockman')
    assert [g['id'] for g in data['games']] == [ids['jp']]
    assert data['games'][0]['version_count'] == 3


# INV-6 — total counts cards, total_roms counts rows, under the same filters.
def test_inv6_total_and_total_roms(group, admin_test_client):
    d, _ = group
    d.game('Solo Game')
    data = _get(admin_test_client, 'USA', f'/api/games?system={d.sid}')
    assert (data['total'], data['total_roms']) == (2, 4)
    data = _get(admin_test_client, 'USA', f'/api/games?system={d.sid}&search=Rockman')
    assert (data['total'], data['total_roms']) == (1, 1)


# §4.3 — bulk select acts on the shown rows, the unscraped filter included.
def test_ids_return_shown_rows_only(group, admin_test_client):
    d, ids = group
    d.game('Solo Game')
    for extra in ('', '&unscraped=1'):
        data = _get(admin_test_client, 'USA', f'/api/games/ids?system={d.sid}{extra}')
        assert len(data['ids']) == 2 and ids['us'] in data['ids']
