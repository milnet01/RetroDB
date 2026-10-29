"""The Systems page's "unscraped" count matches its console page's Unscraped
filter: bonus discs are in neither (reported on Sony PlayStation: 2 unscraped,
filter empty)."""
import re

from tests._versions_util import vdb  # noqa: F401 — fixture


def test_bonus_discs_are_not_counted_unscraped(vdb, admin_test_client):
    vdb.game('Main Game', scraped=1)
    vdb.game('Main Game (Bonus Disc)', scraped=0, is_bonus_disc=1)
    vdb.game('Other Bonus', scraped=0, is_bonus_disc=1)
    client, _ = admin_test_client()
    html = client.get('/systems').get_data(as_text=True)
    card = html[html.index(f'/system/{vdb.sid}"'):]
    card = card[:card.index('</a>')] if '</a>' in card else card
    assert not re.search(r'\d+\s*unscraped', card)

    data = client.get(f'/api/games?system={vdb.sid}&unscraped=1').get_json()
    assert data['total'] == 0


def test_unscraped_games_are_counted(vdb, admin_test_client):
    vdb.game('One', scraped=0)
    vdb.game('Two', scraped=0)
    vdb.game('Bonus', scraped=0, is_bonus_disc=1)
    client, _ = admin_test_client()
    html = client.get('/systems').get_data(as_text=True)
    card = html[html.index(f'/system/{vdb.sid}"'):]
    assert re.search(r'2\s*unscraped', card[:card.index('</a>')])
