"""PASS-59-133 — Full Re-scrape's "keep existing media" option."""
from scraper.hybrid_scraper import _seed_kept_media


def test_seeds_media_on_disk_and_skips_stale_and_text_fields():
    metadata = {'boxart': None, 'fanart': None, 'video': None,
                'screenshots': None, 'description': None}
    game = {'boxart': 'a.png', 'fanart': 'gone.png', 'video': None,
            'screenshots': 'a-1.png, a-2.png', 'description': 'old'}
    _seed_kept_media(metadata, game, {'fanart'})
    assert metadata == {'boxart': 'a.png', 'fanart': None, 'video': None,
                        'screenshots': 'a-1.png, a-2.png', 'description': None}
