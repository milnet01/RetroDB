"""PASS-59-105 — alternate titles tagged by region.

Sources send raw region tags: ScreenScraper short codes and IGDB free-text
comments. They are stored as CLDR territory codes so the game page can name
the region in the user's language.
"""

import pytest

from scraper.metadata_normalizer import (
    alt_title_entry,
    alt_title_region,
    merge_alt_titles,
)
from services.i18n import region_display_name


@pytest.mark.parametrize('raw, expected', [
    ('jp', ('JP', None)),
    ('us', ('US', None)),
    ('eu', ('150', None)),
    ('wor', ('001', None)),
    ('sp', ('ES', None)),
    ('asi', ('142', None)),
    # ScreenScraper's own house name and "custom" are not regions.
    ('ss', (None, None)),
    ('cus', (None, None)),
    # Already-normalized codes pass through, so stored data can be re-run.
    ('JP', ('JP', None)),
    ('150', ('150', None)),
    # IGDB comments: region from the leading word(s), comment kept as a note.
    ('Japanese title - romanization', ('JP', 'Japanese title - romanization')),
    ('North American title', ('US', 'North American title')),
    ('UK title', ('GB', 'UK title')),
    ('Chinese title - traditional', ('CN', 'Chinese title - traditional')),
    ('Acronym', (None, 'Acronym')),
    ('Working title', (None, 'Working title')),
    (None, (None, None)),
    ('  ', (None, None)),
])
def test_alt_title_region(raw, expected):
    assert alt_title_region(raw) == expected


def test_entry_stores_code_and_note():
    assert alt_title_entry('Rockman', region='Japanese title', source='igdb') == {
        'title': 'Rockman', 'region': 'JP', 'note': 'Japanese title', 'source': 'igdb',
    }
    assert alt_title_entry('Angling', region='ss', source='screenscraper') == {
        'title': 'Angling', 'source': 'screenscraper',
    }


def test_merge_normalizes_stored_raw_codes():
    stored = '[{"title": "Rockman", "region": "jp", "source": "screenscraper"}]'
    assert merge_alt_titles(stored, []) == [
        {'title': 'Rockman', 'region': 'JP', 'source': 'screenscraper'},
    ]


def test_merge_adds_region_to_a_name_stored_without_one():
    stored = [{'title': 'Rockman', 'source': 'igdb'}]
    merged = merge_alt_titles(stored, [
        {'title': 'rockman', 'region': 'Japanese title', 'source': 'igdb'},
    ])
    assert merged == [
        {'title': 'Rockman', 'region': 'JP', 'note': 'Japanese title', 'source': 'igdb'},
    ]


def test_merge_keeps_an_existing_region():
    stored = [{'title': 'Rockman', 'region': 'JP'}]
    merged = merge_alt_titles(stored, [{'title': 'Rockman', 'region': 'us'}])
    assert merged == [{'title': 'Rockman', 'region': 'JP'}]


@pytest.mark.parametrize('code, locale, expected', [
    ('JP', 'en', 'Japan'),
    ('JP', 'de', 'Japan'),
    ('150', 'de', 'Europa'),
    ('001', 'en', 'World'),
    ('JP', 'ja', '日本'),
    ('JP', 'xx_bogus', 'Japan'),
    ('ZZZ', 'en', 'ZZZ'),
])
def test_region_display_name(code, locale, expected):
    assert region_display_name(code, locale) == expected
