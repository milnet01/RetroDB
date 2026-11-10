"""PASS-59-298: one spelling per name.

"Doom" on 14 games and "DOOM" on 3 showed as two franchises. Settings >
Normalization now lists such groups for the user to pick a spelling, a new
scraped or AI name takes the library's spelling, and the AI is asked for
official capitals.
"""
import pytest

from scraper.scrape_ai import _build_prompt
from services import normalization
from services.normalization import apply_spellings, case_twin_groups, use_library_spellings
from tests._versions_util import vdb  # noqa: F401 — fixture


@pytest.fixture
def games(vdb):
    d = vdb
    d.ids = {
        'A': d.game('A', franchise='Doom298', publisher='Sega298'),
        'B': d.game('B', franchise='Doom298, Quake298', publisher='Sega298'),
        'C': d.game('C', franchise='DOOM298'),
        'D': d.game('D', franchise='Lone298'),
    }
    normalization.invalidate_normalization_cache()
    yield d
    normalization.invalidate_normalization_cache()


def _franchise(d, key):
    return d.conn.execute("SELECT franchise FROM games WHERE id = ?",
                          (d.ids[key],)).fetchone()[0]


def _group(field, key):
    return [g for g in case_twin_groups(field) if g['suggested'].casefold() == key]


def test_twins_are_listed_most_used_first(games):
    assert _group('franchise', 'doom298') == [{
        'suggested': 'Doom298', 'count': 3,
        'spellings': [{'value': 'Doom298', 'count': 2}, {'value': 'DOOM298', 'count': 1}],
    }]
    # One spelling is not a group.
    assert _group('franchise', 'lone298') == []
    assert _group('franchise', 'quake298') == []


def test_applying_a_spelling_leaves_one_name(games):
    assert apply_spellings('franchise', ['DOOM298']) == 2
    assert _franchise(games, 'A') == 'DOOM298'
    assert _franchise(games, 'B') == 'DOOM298, Quake298'
    assert _franchise(games, 'C') == 'DOOM298'
    assert _franchise(games, 'D') == 'Lone298'
    assert _group('franchise', 'doom298') == []


def test_a_chosen_spelling_cannot_rename(games):
    assert apply_spellings('franchise', ['Quake298 Arena']) == 0
    assert _franchise(games, 'B') == 'Doom298, Quake298'


def test_a_new_name_takes_the_library_spelling(games):
    metadata = {'franchise': 'doom298, New298', 'developer': 'sega298'}
    use_library_spellings(metadata)
    # The developer field has no Sega298; publisher spellings are not borrowed.
    assert metadata == {'franchise': 'Doom298, New298', 'developer': 'sega298'}


def test_a_stored_name_is_kept(games):
    metadata = {'franchise': 'DOOM298'}
    use_library_spellings(metadata, keep={'franchise'})
    assert metadata == {'franchise': 'DOOM298'}


def test_a_company_alias_beats_the_library(games):
    games.game('E', publisher='Sega')
    normalization.invalidate_normalization_cache()
    metadata = {'publisher': 'sega'}
    use_library_spellings(metadata)
    assert metadata == {'publisher': 'SEGA'}


def test_settings_routes(games, admin_test_client):
    client, csrf = admin_test_client(settings={'setup_completed': True})
    headers = {'X-CSRF-Token': csrf}
    groups = client.get('/api/normalize/spellings/franchise').get_json()['groups']
    assert [g['suggested'] for g in groups if g['suggested'] == 'Doom298'] == ['Doom298']
    assert client.get('/api/normalize/spellings/genre').status_code == 400

    resp = client.post('/api/normalize/spellings', json={'field': 'franchise', 'spellings': ['Doom298']},
                       headers=headers)
    assert resp.get_json()['games_updated'] == 1
    assert _franchise(games, 'C') == 'Doom298'
    assert client.post('/api/normalize/spellings',
                       json={'field': 'franchise', 'spellings': []},
                       headers=headers).status_code == 400


@pytest.mark.parametrize('field', ['franchise', 'publisher', 'developer'])
def test_the_ai_is_asked_for_official_capitals(field):
    assert 'official capitals' in _build_prompt('Doom', 'PC', [field])


def test_a_tie_never_picks_all_lowercase(vdb):
    vdb.game('F', franchise='Monster Rancher298')
    vdb.game('G', franchise='monster rancher298')
    normalization.invalidate_normalization_cache()
    assert _group('franchise', 'monster rancher298')[0]['suggested'] == 'Monster Rancher298'
