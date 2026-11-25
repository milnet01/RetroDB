"""A search that finds nothing for a title with accents is asked again
without them (2026-11-25): sources spell 'Ghost of Yōtei' differently."""
import pytest

from scraper import (scrape_esde, scrape_igdb, scrape_mobygames, scrape_rawg,
                     scrape_screenscraper, scrape_thegamesdb)
from scraper.title_normalizer import retry_without_accents, without_accents


def test_accents_are_dropped():
    assert without_accents('Ghost of Yōtei') == 'Ghost of Yotei'
    assert without_accents('Pokémon Rubí') == 'Pokemon Rubi'
    assert without_accents('') == ''


def test_nothing_found_asks_again_without_accents():
    asked = []

    def search(title, system, limit=10):
        asked.append(title)
        return ['hit'] if title == 'Ghost of Yotei' else []

    assert retry_without_accents(search)('Ghost of Yōtei', 'ps5') == ['hit']
    assert asked == ['Ghost of Yōtei', 'Ghost of Yotei']


@pytest.mark.parametrize('title, found', [
    ('Ghost of Yotei', []),        # no accents: asked once
    ('Ghost of Yōtei', ['hit']),   # found: asked once
])
def test_asked_once_otherwise(title, found):
    asked = []

    def search(title, system):
        asked.append(title)
        return found

    retry_without_accents(search)(title, 'ps5')
    assert asked == [title]


@pytest.mark.parametrize('search', [
    scrape_thegamesdb.search_games, scrape_igdb.search_games, scrape_rawg.search_games,
    scrape_mobygames.search_games, scrape_screenscraper.search_game,
    scrape_esde.search_esde_games,
], ids=lambda f: f.__module__)
def test_every_source_retries_without_accents(search):
    assert getattr(search, '__wrapped__', None) is not None
