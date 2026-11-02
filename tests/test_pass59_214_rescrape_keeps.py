"""PASS-59-214: Full Re-scrape overwrites what a source provides and keeps the rest.
Runs the real scrape against a throwaway library; no source has anything to give."""
import json
import os

import pytest

from scraper import hybrid_scraper
from services import game_metadata_service
from tests.test_pass59_205_esde_merge import library  # noqa: F401  (a fixture)

HAND_SET = {'esrb_rating': 'T', 'pegi_rating': '16', 'usk_rating': '16',
            'controller_support': 'Spinner'}


def _scrape(force=False):
    return hybrid_scraper.apply_hybrid_metadata(1, 'esde', 'nothing', 'atari2600',
                                                fill_gaps=False, force_overwrite=force)


def test_full_rescrape_keeps_hand_set_ratings_and_controller(library):  # noqa: F811
    library.add_game(description='A violent war game', genre='Shooter', **HAND_SET)
    _scrape(force=True)
    row = library.row()
    assert {field: row[field] for field in HAND_SET} == HAND_SET


def test_full_rescrape_does_not_guess_a_rating_over_one_board(library):  # noqa: F811
    library.add_game(pegi_rating='3', description='A violent war game', genre='Shooter')
    _scrape(force=True)
    assert library.row()['pegi_rating'] == '3'


def test_a_fill_missing_scrape_still_guesses_an_empty_controller(library):  # noqa: F811
    library.add_game()
    _scrape()
    assert library.row()['controller_support']


def test_history_records_the_ratings_steps(library):  # noqa: F811
    library.add_game(description='A violent war game', genre='Shooter')
    _scrape()
    row = library.row()
    history = json.loads(row['scrape_history'])
    assert row['esrb_rating'], 'this test needs a guessed rating'
    assert 'ratings (inferred from content)' in history[-1]['fields_filled']


def test_keep_media_seeds_only_screenshots_on_disk(tmp_path, monkeypatch):
    monkeypatch.setattr(hybrid_scraper, 'IMAGE_PATH', str(tmp_path))
    os.makedirs(tmp_path / 'screenshots')
    (tmp_path / 'screenshots' / 'here.webp').write_bytes(b'x')
    monkeypatch.setattr(hybrid_scraper, 'media_dir_is_healthy', lambda path: True)
    metadata = {field: None for field in hybrid_scraper._KEPT_MEDIA_FIELDS}
    hybrid_scraper._seed_kept_media(metadata, {'screenshots': 'here.webp, gone.webp'}, ())
    assert metadata['screenshots'] == 'here.webp'


def test_a_failed_scrape_writes_nothing_by_a_second_route(monkeypatch):
    called = []

    def fails(*args, **kwargs):
        raise RuntimeError('boom')

    monkeypatch.setattr('scraper.hybrid_scraper.apply_hybrid_metadata', fails)
    monkeypatch.setattr(game_metadata_service, 'apply_metadata_to_game',
                        lambda *a, **k: called.append(a) or True)
    monkeypatch.setattr('scraper.scraper_manager.scraper_manager.fetch_game_details',
                        lambda *a, **k: {'name': 'Game'})
    found = game_metadata_service.apply_hybrid_metadata_to_game(1, 'igdb', 5, 'atari2600')
    assert found['success'] is False
    assert not called
