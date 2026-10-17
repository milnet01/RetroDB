"""PASS-59-110: sequels must not share one RetroAchievements game id.

Both RA matchers dropped one-character words, so the sequel number in
"Donkey Kong Country 2" vanished and the title matched "Donkey Kong
Country". A sequel number (2, II, 3, III ...) is part of a title's
identity: a numbered title must not match an unnumbered one, or one with
a different number.

The RA game lists below are built by hand; no network call is made.
"""
import pytest

from scraper import retroachievements as ra
from services.achievement_linking import match_ra_game


def _ra(game_id, title):
    return {'ID': game_id, 'Title': title, 'NumAchievements': 10, 'Points': 100}


# Unnumbered entries listed first: a matcher that ignores the number
# returns the first entry it sees, which is how the bug showed up.
RA_GAMES = [
    _ra(750, 'Donkey Kong Country'),
    _ra(751, "Donkey Kong Country 2: Diddy's Kong Quest"),
    _ra(752, "Donkey Kong Country 3: Dixie Kong's Double Trouble!"),
    _ra(528, 'Doom'),
    _ra(529, 'Doom II'),
    _ra(793, 'Sonic Advance'),
    _ra(794, 'Sonic Advance 2'),
    _ra(795, 'Sonic Advance 3'),
    _ra(100, 'Legend of Zelda, The: A Link to the Past'),
    _ra(200, 'Mega Man Battle Network'),
    _ra(201, 'Mega Man Battle Network 2'),
]

CASES = [
    # Sequels must resolve to their own set.
    ("Donkey Kong Country 2 - Diddy's Kong Quest (USA)", 751),
    ("Donkey Kong Country 3 - Dixie Kong's Double Trouble! (USA)", 752),
    ('Doom 2', 529),
    ('Doom II (USA)', 529),
    ('Sonic Advance 2 (USA)', 794),
    ('Sonic Advance 3 (Europe)', 795),
    ('Mega Man Battle Network 2 (USA)', 201),
    # Positive controls: unnumbered titles, region suffixes, articles.
    ('Donkey Kong Country (USA)', 750),
    ('DOOM', 528),
    ('Sonic Advance (Europe)', 793),
    ('Mega Man Battle Network (USA)', 200),
]

# A numbered local title whose sequel has no RA set must stay unlinked,
# not borrow the first game's set.
UNMATCHED = [
    'Donkey Kong Country 2',          # live-DB title; RA set carries a subtitle
    'Sonic Advance 4 (USA)',
    'Mega Man Battle Network 3 (USA)',
]


@pytest.mark.parametrize('title,expected', CASES)
def test_refresh_matcher_keeps_sequels_apart(title, expected):
    match = match_ra_game(title, '', RA_GAMES)
    assert match is not None, title
    assert match['ID'] == expected, (title, match['Title'])


@pytest.mark.parametrize('title', UNMATCHED)
def test_refresh_matcher_rejects_wrong_sequel(title):
    match = match_ra_game(title, '', RA_GAMES)
    assert match is None, (title, match and match['Title'])


def test_refresh_matcher_article_control():
    match = match_ra_game('The Legend of Zelda - A Link to the Past (USA)', '', RA_GAMES)
    assert match is not None and match['ID'] == 100


@pytest.fixture
def scraper_search(monkeypatch):
    """search_game_by_name against the hand-built list, no network."""
    monkeypatch.setattr(ra, 'get_ra_credentials', lambda: ('user', 'key'))
    monkeypatch.setattr(ra, '_ra_cache_get', lambda console_id: RA_GAMES)

    def _fail(*a, **k):
        raise AssertionError('network call attempted')
    monkeypatch.setattr(ra, 'http_get', _fail)
    return lambda title: ra.search_game_by_name(title, 3)


@pytest.mark.parametrize('title,expected', CASES)
def test_scrape_matcher_keeps_sequels_apart(scraper_search, title, expected):
    result = scraper_search(title)
    assert result is not None, title
    assert result['id'] == expected, (title, result['title'])


@pytest.mark.parametrize('title', UNMATCHED)
def test_scrape_matcher_rejects_wrong_sequel(scraper_search, title):
    result = scraper_search(title)
    assert result is None, (title, result and result['title'])
