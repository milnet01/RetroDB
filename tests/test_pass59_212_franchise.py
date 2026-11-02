"""PASS-59-212: a franchise comes from a source that names one, never from a title.
The examples are the ones the PASS-59-162 review found. No test reaches a service."""
import collections
import json
import sqlite3

import pytest

from scraper import hybrid_scraper, metadata_merger, scrape_rawg, scrape_screenscraper
from services import migrations


def test_thegamesdb_gives_no_franchise(monkeypatch):
    monkeypatch.setattr(hybrid_scraper, 'fetch_tgdb_details',
                        lambda game_id: {'name': 'Mission: Impossible'})
    details = hybrid_scraper.fetch_tgdb_extended(1)
    assert details['name'] == 'Mission: Impossible'
    assert '_extended' not in details


def test_rawg_gives_no_franchise_and_spends_no_request_on_one(monkeypatch):
    asked = []

    def fake_request(endpoint, params=None):
        asked.append(endpoint)
        return {'id': 7, 'name': 'Need For Speed Carbon'} if endpoint == 'games/7' else {
            'count': 1, 'results': [{'name': 'Need For Speed: Most Wanted'}]}

    monkeypatch.setattr(scrape_rawg, '_make_request', fake_request)
    details = scrape_rawg.get_game_details(7)
    assert 'franchise' not in details
    assert not [e for e in asked if 'game-series' in e]


def _igdb(monkeypatch, record):
    bodies = []
    monkeypatch.setattr(hybrid_scraper, 'igdb_auth', lambda: 't')
    monkeypatch.setattr(hybrid_scraper, 'igdb_request',
                        lambda endpoint, body, token: bodies.append(body) or [record])
    return hybrid_scraper.fetch_igdb_extended(1)['_extended']['franchise'], bodies[0]


def test_igdb_series_name_comes_from_collections(monkeypatch):
    # IGDB's reply for the OutRun game the review sampled.
    franchise, body = _igdb(monkeypatch, {'collections': [{'id': 379, 'name': 'OutRun'}]})
    assert franchise == 'OutRun'
    assert 'collections.name' in body
    assert 'collection.name' not in body


def test_igdb_prefers_a_named_franchise_over_a_collection(monkeypatch):
    franchise, _ = _igdb(monkeypatch, {'franchise': {'name': 'Sonic'},
                                       'collections': [{'name': 'Sonic 2D'}]})
    assert franchise == 'Sonic'
    franchise, _ = _igdb(monkeypatch, {'franchises': [{'name': 'Mario'}],
                                       'collections': [{'name': 'Mario Kart'}]})
    assert franchise == 'Mario'


def test_screenscraper_repeat_is_kept_once():
    parsed = scrape_screenscraper.parse_game_data({'familles': [
        {'noms': [{'langue': 'fr', 'text': 'Centipede'}]},
        {'noms': [{'langue': 'fr', 'text': 'Atari'}]},
        {'noms': [{'langue': 'fr', 'text': 'Centipede'}]},
    ]})
    assert parsed['franchise'] == 'Centipede, Atari'


def test_screenscraper_merge_keeps_a_repeat_once():
    metadata = collections.defaultdict(lambda: None)
    result = {'filled_fields': []}
    metadata_merger.apply_screenscraper_to_metadata(
        metadata,
        {'familles': [{'noms': [{'langue': 'en', 'text': 'Alien'}]},
                      {'noms': [{'langue': 'en', 'text': 'Alien'}]}]},
        db_game_id=1, result=result)
    assert metadata['franchise'] == 'Alien'


# --- stored rows --------------------------------------------------------------

def _credit(*sources):
    return json.dumps([{'fields_filled': [f'franchise ({s})']} for s in sources])


@pytest.mark.parametrize('title,franchise,history,kept', [
    # Guesses a scrape wrote: each is the start of the title.
    ('Alien 8', 'Alien', _credit('TGDB'), None),
    ('Need For Speed Carbon', 'Need', _credit('RAWG'), None),
    ('Jet Set Radio', 'JET', _credit('RAWG'), None),
    # Credited to a guesser, but not cut from this title: a person typed it.
    ('Crash Team Racing', 'Crash Bandicoot', _credit('RAWG'), 'Crash Bandicoot'),
    # Sources that name a series.
    ('OutRun 2', 'OutRun', _credit('IGDB'), 'OutRun'),
    ('Alien 8', 'Alien', _credit('ScreenScraper'), 'Alien'),
    # The newest credit decides.
    ('Alien 8', 'Alien', _credit('TGDB', 'AI'), 'Alien'),
    ('Alien 8', 'Alien', _credit('AI', 'TGDB'), None),
    # No credit at all, or history that cannot be read.
    ('Alien 8', 'Alien', None, 'Alien'),
    ('Alien 8', 'Alien', 'not json', 'Alien'),
    # A repeated name is kept once, and a list without a repeat is left alone.
    ('Centipede', 'Centipede, Centipede', _credit('ScreenScraper'), 'Centipede'),
    ('Sponge', 'Spongebob, Nickelodeon, spongebob', _credit('ScreenScraper'), 'Spongebob, Nickelodeon'),
    ('Sponge', 'Spongebob, Nickelodeon', _credit('ScreenScraper'), 'Spongebob, Nickelodeon'),
])
def test_migration_clears_only_guesses(title, franchise, history, kept):
    conn = sqlite3.connect(':memory:')
    conn.execute('CREATE TABLE games (id INTEGER PRIMARY KEY, title TEXT, franchise TEXT, scrape_history TEXT)')
    conn.execute('INSERT INTO games (title, franchise, scrape_history) VALUES (?, ?, ?)',
                 (title, franchise, history))
    migrations._load('029_clear_franchise_guesses').apply(conn)
    assert conn.execute('SELECT franchise FROM games').fetchone()[0] == kept


def test_migration_runs_on_a_database_with_no_games_table():
    migrations._load('029_clear_franchise_guesses').apply(sqlite3.connect(':memory:'))
