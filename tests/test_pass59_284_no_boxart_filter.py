"""PASS-59-284 — the dashboard's "Games missing box art" opens the Library
filtered to them (?no_boxart=1); it used to open the whole Library."""

from tests._versions_util import vdb  # noqa: F401 — fixture


def _titles(admin_test_client, path):
    client, _ = admin_test_client(settings={'setup_completed': True})
    resp = client.get(path)
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    return [g['title'] for g in resp.get_json()['games']]


def test_no_boxart_shows_only_games_without_one(vdb, admin_test_client):
    vdb.game('Alpha', boxart='1_ss_boxart.webp')
    vdb.game('Bravo', boxart='')
    vdb.game('Charlie')
    assert _titles(admin_test_client, f'/api/games?system={vdb.sid}&no_boxart=1') == ['Bravo', 'Charlie']
    assert _titles(admin_test_client, f'/api/games?system={vdb.sid}') == ['Alpha', 'Bravo', 'Charlie']


def test_dashboard_link_asks_for_the_filter():
    from tests._util import read_source
    assert "url_for('games.all_games', no_boxart=1)" in read_source('templates/dashboard.html')
