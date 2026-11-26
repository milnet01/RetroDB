"""Sales figures (games.units_sold), asked of the AI during a scrape and by
AI Fill."""
import inspect

import pytest

from scraper import scrape_ai
from scraper.scrape_ai import parse_units_sold
from tests.test_pass59_205_esde_merge import library  # noqa: F401  (fixture)
from tests.test_pass59_242_user_edits import _ai_fill, _scrape


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


def test_ai_fill_stores_sales_as_an_integer(library, monkeypatch):
    library.add_game()
    _ai_fill(monkeypatch, {'units_sold': '2400000'})  # as scrape_ai validates it
    assert library.row()['units_sold'] == 2400000


@pytest.mark.parametrize('force', [False, True])
def test_a_scrape_with_no_sales_keeps_the_stored_figure(library, force):
    # The save wraps units_sold in COALESCE: a source with nothing never wipes it.
    library.add_game(units_sold=5)
    _scrape(force=force)
    assert library.row()['units_sold'] == 5


def test_ai_gap_fill_writes_sales_as_int():
    from scraper.metadata_merger import apply_ai_to_metadata
    metadata = {'units_sold': None}
    result = {'filled_fields': []}
    apply_ai_to_metadata(metadata, {'units_sold': '2400000'}, 1, result)
    assert metadata['units_sold'] == 2400000
    metadata = {'units_sold': 5}
    apply_ai_to_metadata(metadata, {'units_sold': '2400000'}, 1, {'filled_fields': []})
    assert metadata['units_sold'] == 5


# --- PASS-59-343: sales asked on their own, and an all-console total ----------

def _fake_ai(monkeypatch, replies):
    """get_game_details with a fake Claude: each call takes the next reply and
    records its prompt and whether it searched."""
    calls = []
    monkeypatch.setattr(scrape_ai, '_get_active_provider', lambda: {
        'provider': 'claude', 'api_key': 'k', 'model': 'm', 'web_search': True})
    monkeypatch.setattr(scrape_ai, 'rate_limit', lambda **k: None)
    monkeypatch.setattr(scrape_ai, '_official_title_context', lambda game_id: None)

    def call(prompt, key, model, web_search=False, **k):
        calls.append({'prompt': prompt, 'search': web_search})
        return replies[len(calls) - 1]
    monkeypatch.setattr(scrape_ai, '_call_claude', call)
    return calls


def test_sales_are_asked_in_their_own_call(monkeypatch):
    calls = _fake_ai(monkeypatch, [
        '{"genre": "Racing"}',
        '{"units_sold": "2.9 million", "all_platforms_units": null, "all_platforms": ""}'])
    result = scrape_ai.get_game_details(1, 'Going Commando', 'PlayStation 2',
                                        existing_metadata={})
    assert len(calls) == 2
    combined, sales = calls
    assert '"units_sold"' not in combined['prompt'] and '"genre"' in combined['prompt']
    assert '"units_sold"' in sales['prompt'] and sales['search']
    assert result['units_sold'] == '2900000' and result['genre'] == 'Racing'
    assert 'sales_all_platforms' not in result


def test_only_sales_missing_makes_one_call(monkeypatch):
    calls = _fake_ai(monkeypatch, ['{"units_sold": 850000}'])
    result = scrape_ai.get_game_details(1, 'Castlevania III', 'NES', existing_metadata={},
                                        only_fields=['units_sold'])
    assert len(calls) == 1 and result == {'units_sold': '850000'}


def test_a_filled_figure_is_not_asked(monkeypatch):
    calls = _fake_ai(monkeypatch, ['{"genre": "Racing"}'])
    scrape_ai.get_game_details(1, 'X', 'PS2', existing_metadata={'units_sold': '5000'},
                               only_fields=['genre', 'units_sold'])
    assert len(calls) == 1 and '"units_sold"' not in calls[0]['prompt']


def test_an_all_console_total_is_kept_apart(monkeypatch):
    _fake_ai(monkeypatch, [
        '{"units_sold": null, "all_platforms_units": "8 million", '
        '"all_platforms": "PS4, Xbox One, PC"}'])
    result = scrape_ai.get_game_details(1, 'Battlefield Hardline', 'PlayStation 4',
                                        existing_metadata={}, only_fields=['units_sold'])
    assert 'units_sold' not in result
    import json
    assert json.loads(result['sales_all_platforms']) == {
        'units': 8000000, 'platforms': 'PS4, Xbox One, PC'}


def test_a_rejected_answer_is_logged_word_for_word(monkeypatch, caplog):
    _fake_ai(monkeypatch, ['{"units_sold": "between 1 and 2 million"}'])
    with caplog.at_level('INFO', logger=scrape_ai.logger.name):
        result = scrape_ai.get_game_details(1, 'Gungrave', 'PlayStation 2',
                                            existing_metadata={}, only_fields=['units_sold'])
    assert result == {}
    assert 'between 1 and 2 million' in caplog.text


def test_gap_fill_and_ai_fill_save_the_total(library, monkeypatch):
    from scraper.metadata_merger import apply_ai_to_metadata
    total = '{"units": 8000000, "platforms": "PS4, Xbox One, PC"}'
    metadata = {'sales_all_platforms': None}
    apply_ai_to_metadata(metadata, {'sales_all_platforms': total}, 1, {'filled_fields': []})
    assert metadata['sales_all_platforms'] == total
    library.add_game()
    _ai_fill(monkeypatch, {'sales_all_platforms': total})
    assert library.row()['sales_all_platforms'] == total


@pytest.mark.parametrize('force', [False, True])
def test_a_scrape_keeps_a_stored_total(library, force):
    library.add_game(sales_all_platforms='{"units": 9000}')
    _scrape(force=force)
    assert library.row()['sales_all_platforms'] == '{"units": 9000}'


def test_ai_fill_with_only_sales_ticked_keeps_the_total(library, monkeypatch):
    library.add_game()
    total = '{"units": 8000000, "platforms": "PS4, PC"}'
    monkeypatch.setattr('scraper.scrape_ai.get_game_details',
                        lambda *a, **k: {'sales_all_platforms': total})
    monkeypatch.setattr('scraper.hybrid_scraper.get_system_default_controller_name',
                        lambda system_id: None)
    from services import ai_fill
    ai_fill.fill_game(ai_fill.load_game(1), fields=ai_fill.columns_for(['units_sold']))
    assert library.row()['sales_all_platforms'] == total


def test_analytics_lists_best_sellers_and_totals_once(library):
    from services.analytics import _get_sales_data
    total = '{"units": 8000000, "platforms": "PS4, Xbox One, PC"}'
    library.add_game('a.iso', id=1, title='Hardline', sales_all_platforms=total)
    library.add_game('b.iso', id=2, title='Hardline', sales_all_platforms=total)  # another console's row
    library.add_game('c.iso', id=3, title='Going Commando', units_sold=2966000)
    library.add_game('d.iso', id=4, title='Gungrave', units_sold=190000)
    count, best, totals = _get_sales_data()
    assert count == 2
    assert [g['title'] for g in best] == ['Going Commando', 'Gungrave']
    assert [(g['title'], g['units'], g['platforms']) for g in totals] == [
        ('Hardline', 8000000, 'PS4, Xbox One, PC')]


def test_the_analytics_page_shows_the_sales_section(library, admin_test_client):
    from services.analytics import invalidate_analytics_cache
    library.add_game('c.iso', id=3, title='Going Commando', units_sold=2966000)
    library.add_game('a.iso', id=1, title='Hardline',
                     sales_all_platforms='{"units": 8000000, "platforms": "PS4, PC"}')
    invalidate_analytics_cache()
    client, _ = admin_test_client()
    html = client.get('/analytics').get_data(as_text=True)
    assert 'href="#sales"' in html and 'id="sales"' in html
    assert 'Going Commando' in html and 'PS4, PC' in html


def test_the_sales_section_says_when_it_has_nothing(library, admin_test_client):
    from services.analytics import invalidate_analytics_cache
    library.add_game()
    invalidate_analytics_cache()
    client, _ = admin_test_client()
    html = client.get('/analytics').get_data(as_text=True)
    assert 'No sales figures yet.' in html and 'No all-platform totals yet.' in html
