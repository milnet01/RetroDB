"""PASS-59-300: one company under different names.

"Eidos" and "Eidos Interactive" showed as two publishers. Settings >
Normalization now suggests names that look like one company; the user picks
the name to keep and ticks the ones to merge. Nothing merges by itself, and
later scrapes take the kept name.
"""
import pytest

from services import normalization
from services.normalization import (
    canonical_companies, company_lookalike_groups, merge_companies, use_library_spellings,
)
from tests._versions_util import vdb  # noqa: F401 — fixture


@pytest.fixture(autouse=True)
def _fresh_aliases():
    # A merge is cached for a while; never let one reach another test.
    normalization.invalidate_normalization_cache()
    yield
    normalization.invalidate_normalization_cache()


@pytest.fixture
def games(vdb):
    d = vdb
    d.ids = {
        'A': d.game('A', publisher='Eidos300', developer='Core300'),
        'B': d.game('B', publisher='Eidos300 Interactive', developer='Eidos300'),
        'C': d.game('C', publisher='Eidos300 Interactive, Ltd.'),
        'D': d.game('D', publisher='EIDOS300'),
        'E': d.game('E', publisher='Other300 Games'),
    }
    normalization.invalidate_normalization_cache()
    return d


def _get(d, key, field='publisher'):
    return d.conn.execute(f"SELECT {field} FROM games WHERE id = ?",
                          (d.ids[key],)).fetchone()[0]


def _group(field, word):
    return [g for g in company_lookalike_groups(field)
            if any(word in n['value'].casefold() for n in g['names'])]


def test_look_alikes_are_listed_most_used_first(games):
    assert _group('publisher', 'eidos300') == [{
        'suggested': 'Eidos300', 'count': 4,
        'names': [{'value': 'Eidos300', 'count': 2},
                  {'value': 'Eidos300 Interactive', 'count': 1},
                  {'value': 'Eidos300 Interactive, Ltd.', 'count': 1}],
    }]
    # One name alone is not a group, and a company word alone makes no name.
    assert _group('publisher', 'other300') == []
    assert _group('developer', 'core300') == []


def test_listing_merges_nothing(games):
    company_lookalike_groups('publisher')
    assert _get(games, 'B') == 'Eidos300 Interactive'


def test_merging_rewrites_both_fields(games):
    assert merge_companies('Eidos300 Interactive', ['Eidos300', 'Eidos300 Interactive, Ltd.']) == 4
    for key in 'ABCD':
        assert _get(games, key) == 'Eidos300 Interactive'
    assert _get(games, 'B', 'developer') == 'Eidos300 Interactive'
    assert _get(games, 'A', 'developer') == 'Core300'
    assert _get(games, 'E') == 'Other300 Games'
    assert _group('publisher', 'eidos300') == []


def test_unticked_names_stay(games):
    assert merge_companies('Eidos300', ['Eidos300 Interactive']) == 1
    assert _get(games, 'B') == 'Eidos300'
    assert _get(games, 'C') == 'Eidos300 Interactive, Ltd.'


def test_a_merge_of_only_the_kept_name_does_nothing(games):
    assert merge_companies('Eidos300', ['eidos300', ' ']) == 0
    assert merge_companies('', ['Eidos300']) == 0


def test_later_scrapes_take_the_kept_name(games):
    merge_companies('Eidos300 Interactive', ['Eidos300'])
    assert canonical_companies('eidos300, Core300') == 'Eidos300 Interactive, Core300'
    metadata = {'developer': 'EIDOS300'}
    use_library_spellings(metadata)
    assert metadata == {'developer': 'Eidos300 Interactive'}


def test_a_merge_can_reverse_a_built_in_alias(vdb):
    # The built-in list turns "Acclaim" into "Acclaim Entertainment".
    assert canonical_companies('Acclaim') == 'Acclaim Entertainment'
    merge_companies('Acclaim', ['Acclaim Entertainment'])
    assert canonical_companies('Acclaim, Acclaim Entertainment') == 'Acclaim'


def test_a_later_merge_follows_an_earlier_one(vdb):
    merge_companies('Eidos300 Interactive', ['Eidos300'])
    merge_companies('Eidos300 Ltd', ['Eidos300 Interactive'])
    assert canonical_companies('Eidos300') == 'Eidos300 Ltd'


def test_settings_routes(games, admin_test_client):
    client, csrf = admin_test_client(settings={'setup_completed': True})
    headers = {'X-CSRF-Token': csrf}
    groups = client.get('/api/normalize/companies/publisher').get_json()['groups']
    assert [g['suggested'] for g in groups if g['suggested'] == 'Eidos300'] == ['Eidos300']
    assert client.get('/api/normalize/companies/franchise').status_code == 400

    resp = client.post('/api/normalize/companies',
                       json={'keep': 'Eidos300', 'merge': ['Eidos300 Interactive']},
                       headers=headers)
    assert resp.get_json()['games_updated'] == 1
    assert _get(games, 'B') == 'Eidos300'
    for bad in ({'keep': 'Eidos300', 'merge': []}, {'keep': '', 'merge': ['X']},
                {'keep': 'Eidos300', 'merge': 'Eidos300 Interactive'}):
        assert client.post('/api/normalize/companies', json=bad,
                           headers=headers).status_code == 400
