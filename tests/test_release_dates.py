"""Release dates by region (games.release_dates): parsing what the AI
returns, storing it fill-only, and showing it."""
import json

from scraper.scrape_ai import AI_FILLABLE_FIELDS, _build_prompt, _validate_field
from services.release_dates import (
    display_release_dates, parse_release_dates, release_dates_json,
)


def test_parse_takes_codes_names_and_lists():
    assert parse_release_dates({'Japan': '2002-11-17', 'north america': '2002-11-18',
                                'PAL': '2003-03'}) \
        == {'NA': '2002-11-18', 'EU': '2003-03', 'JP': '2002-11-17'}
    assert parse_release_dates([{'region': 'JP', 'date': '2002'}]) == {'JP': '2002'}
    assert parse_release_dates('{"KR": "2004/05/06"}') == {'KR': '2004-05-06'}


def test_parse_drops_bad_regions_and_dates():
    assert parse_release_dates({'Mars': '2002-01-01', 'JP': '2002-02-30',
                                'NA': 'soon', 'EU': '1890', 'AU': '3999-01-01'}) == {}
    assert parse_release_dates('not json') == {}
    assert parse_release_dates(None) == {}
    assert parse_release_dates(['JP']) == {}


def test_stored_as_compact_json_in_region_order():
    assert release_dates_json({'JP': '2002-11-17', 'NA': '2002-11-18'}) \
        == '{"NA":"2002-11-18","JP":"2002-11-17"}'
    assert release_dates_json({}) is None


def test_ai_field_is_asked_for_and_validated():
    assert 'release_dates' in AI_FILLABLE_FIELDS
    prompt = _build_prompt('Metroid Prime', 'Nintendo GameCube', ['release_dates'])
    assert '"release_dates"' in prompt and 'Nintendo GameCube' in prompt
    value = _validate_field('release_dates', {'JP': '2003-02-28', 'NA': '2002-11-17'})
    assert json.loads(value) == {'NA': '2002-11-17', 'JP': '2003-02-28'}
    assert _validate_field('release_dates', {}) == ''
    assert _validate_field('release_dates', 'unknown') == ''


def test_gap_fill_never_replaces_stored_dates():
    from scraper.metadata_merger import apply_ai_to_metadata
    result = {'filled_fields': []}
    metadata = {'release_dates': '{"JP":"2002-11-17"}'}
    apply_ai_to_metadata(metadata, {'release_dates': '{"NA":"2002-11-18"}'}, 1, result)
    assert metadata['release_dates'] == '{"JP":"2002-11-17"}'
    metadata = {'release_dates': None}
    apply_ai_to_metadata(metadata, {'release_dates': '{"NA":"2002-11-18"}'}, 1, result)
    assert metadata['release_dates'] == '{"NA":"2002-11-18"}'
    assert 'release_dates (AI)' in result['filled_fields']


def test_hybrid_save_writes_the_column_fill_only():
    from tests._util import read_source
    src = read_source('scraper/hybrid_scraper.py')
    assert 'release_dates = COALESCE(?, release_dates)' in src


def test_display_is_earliest_first_and_localised():
    rows = display_release_dates('{"NA":"2002-11-18","EU":"2003","JP":"2002-11-17"}', 'en')
    assert [r['code'] for r in rows] == ['JP', 'NA', 'EU']
    assert rows[0]['region'] == 'Japan' and rows[0]['date'] == 'Nov 17, 2002'
    assert rows[1]['region'] == 'North America'
    assert rows[2]['date'] == '2003'
    de = display_release_dates('{"EU":"2003-03"}', 'de')
    assert de[0]['region'] == 'Europa'
