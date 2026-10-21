# =============================================================================
# PASS-59-147 — ScreenScraper needs a space before a title's colon
# =============================================================================
# Probed live on 2026-10-21: ScreenScraper's search finds nothing for
# "Alone in the Dark: The New Nightmare" and finds it for
# "Alone in the Dark : The New Nightmare". Every colon title probed behaved
# the same; the part before the colon found each one too. Dropping an
# apostrophe, hyphen, "&", "*" or accent made it find nothing, so those stay.
# =============================================================================

import json

import pytest

from tests._util import REPO_ROOT  # noqa: F401  (ensures sys.path is set)


class _Reply:
    def __init__(self, games):
        self.status_code = 200
        self.text = json.dumps({'response': {'jeux': games}}) if games else ''

    def json(self):
        return json.loads(self.text)


@pytest.fixture
def ss(monkeypatch):
    """search_game against a fake ScreenScraper that knows one spelling."""
    from scraper import scrape_screenscraper
    sent = []
    known = {}

    def fake_request(url, params, timeout):
        query = dict(params)['recherche']
        sent.append(query)
        return _Reply(known.get(query))

    monkeypatch.setattr(scrape_screenscraper, '_ss_request_with_retry', fake_request)
    monkeypatch.setattr(scrape_screenscraper, 'get_system_id', lambda folder: 57)

    def search(title, finds):
        known.clear()
        known.update(finds)
        return scrape_screenscraper.search_game(title, 'psx', 'u', 'p'), sent
    yield search


GAME = [{'id': 1, 'noms': [{'text': 'Alone in the Dark : The New Nightmare'}]}]


def test_a_colon_gets_a_space_before_it(ss):
    results, sent = ss('Alone in the Dark: The New Nightmare',
                       {'Alone in the Dark : The New Nightmare': GAME})
    assert results == GAME
    assert sent == ['Alone in the Dark : The New Nightmare']


def test_a_spaced_dash_is_searched_as_a_colon(ss):
    results, sent = ss('Alone in the Dark - The New Nightmare',
                       {'Alone in the Dark : The New Nightmare': GAME})
    assert results == GAME
    assert sent == ['Alone in the Dark : The New Nightmare']


def test_the_part_before_the_colon_is_tried_when_the_whole_title_finds_nothing(ss):
    results, sent = ss('Alone in the Dark: New Nightmare',
                       {'Alone in the Dark': GAME})
    assert results == GAME
    assert sent == ['Alone in the Dark : New Nightmare', 'Alone in the Dark']


@pytest.mark.parametrize('title', ["Tony Hawk's Pro Skater 2", 'Spider-Man',
                                   'Ratchet & Clank', 'Q*bert', 'Pokémon Snap'])
def test_other_punctuation_is_sent_as_written(ss, title):
    results, sent = ss(title, {})
    assert results is None
    assert sent == [title]
