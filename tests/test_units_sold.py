"""Sales figures (games.units_sold), asked of the AI during a scrape and by
AI Fill."""
import inspect

import pytest

from scraper import scrape_ai
from scraper.scrape_ai import parse_units_sold


@pytest.mark.parametrize('raw,expected', [
    (2400000, 2400000),
    ('2400000', 2400000),
    ('2,400,000', 2400000),
    ('850,000', 850000),
    ('2.4 million', 2400000),
    ('2,4 million', 2400000),
    ('2.4M', 2400000),
    ('~850k', 850000),
    ('over 1 million', 1000000),
    ('3.5 million copies', 3500000),
    ('2,400 thousand', 2400000),
    ('1,500k', 1500000),
    ('1,5 million', 1500000),
    ('1,234.5 thousand', 1234500),
])
def test_parses_what_an_ai_writes(raw, expected):
    assert parse_units_sold(raw) == expected


@pytest.mark.parametrize('raw', [None, '', 'unknown', 0, -5, '0', True, '1 billion', 'lots'])
def test_rejects_unknown_or_impossible(raw):
    assert parse_units_sold(raw) is None


def test_ai_is_asked_for_sales():
    assert 'units_sold' in scrape_ai.AI_FILLABLE_FIELDS
    prompt = scrape_ai._build_prompt('Halo 3', 'Xbox 360', ['units_sold'])
    assert '"units_sold"' in prompt and 'Xbox 360' in prompt
    assert scrape_ai._validate_field('units_sold', '1.2 million') == '1200000'
    assert scrape_ai._validate_field('units_sold', 'n/a') == ''


def test_ai_fill_uses_the_shared_field_list():
    from routes import games_ai
    src = inspect.getsource(games_ai.api_game_ai_fill)
    assert 'ai_fields = AI_FILLABLE_FIELDS' in src
    assert "'units_sold'" in src  # stored as an integer


def test_scrape_fills_sales_only_when_empty():
    from scraper import hybrid_scraper
    src = inspect.getsource(hybrid_scraper)
    assert 'units_sold = COALESCE(?, units_sold)' in src


def test_ai_gap_fill_writes_sales_as_int():
    from scraper.metadata_merger import apply_ai_to_metadata
    metadata = {'units_sold': None}
    result = {'filled_fields': []}
    apply_ai_to_metadata(metadata, {'units_sold': '2400000'}, 1, result)
    assert metadata['units_sold'] == 2400000
    metadata = {'units_sold': 5}
    apply_ai_to_metadata(metadata, {'units_sold': '2400000'}, 1, {'filled_fields': []})
    assert metadata['units_sold'] == 5
