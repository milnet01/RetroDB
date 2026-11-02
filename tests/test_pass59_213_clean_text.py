"""PASS-59-213: text arrives clean and in the right language, and stored rows are
tidied once. The examples are the ones the PASS-59-162 review found. No test
reaches a service."""
import collections
import json
import sqlite3

import pytest

from scraper import hybrid_scraper, metadata_merger, metadata_normalizer, scrape_esde, scrape_igdb, scrape_rawg, scrape_screenscraper
from services import migrations
from services.normalization import canonical_companies, canonicalize_metadata, clean_description


@pytest.mark.parametrize('raw,clean', [
    ('The &quot;hub&quot; area scrolls', 'The "hub" area scrolls'),
    ('###Plot\nSonic runs.\n###Gameplay\nFast.', 'Plot\nSonic runs.\nGameplay\nFast.'),
    ('###Features:\n* Guns\n* Cars', 'Features:\nGuns\nCars'),
    ('Out Run[a] is a racer[12].', 'Out Run is a racer.'),
    ('First line.\r\nSecond line. \r\n', 'First line.\nSecond line.'),
    # Text that only looks like marks stays.
    ('C# and 5 * 3 [see manual]', 'C# and 5 * 3 [see manual]'),
])
def test_clean_description(raw, clean):
    assert clean_description(raw) == clean


@pytest.mark.parametrize('raw,clean', [
    ('Sega', 'SEGA'), ('SEGA', 'SEGA'), ('Ubi Soft', 'Ubisoft'),
    ('Ubisoft Entertainment', 'Ubisoft'), ('Ubi Soft Entertainment Software', 'Ubisoft'),
    ('Acclaim', 'Acclaim Entertainment'), ('Ocean Software Ltd.', 'Ocean'),
    ('Sega, SEGA', 'SEGA'),
    # Separate companies stay separate.
    ('Atari, Inc.', 'Atari, Inc.'), ('Atari Games', 'Atari Games'), ('Sega of America', 'Sega of America'),
    ('989', '989'),
])
def test_company_names(raw, clean):
    assert canonical_companies(raw) == clean


def test_the_save_step_cleans_description_and_companies():
    metadata = {'description': '###Plot\r\nRuns.', 'publisher': 'Sega', 'developer': 'Ubi Soft'}
    canonicalize_metadata(metadata)
    assert metadata == {'description': 'Plot\nRuns.', 'publisher': 'SEGA', 'developer': 'Ubisoft'}


def test_a_description_of_only_marks_leaves_the_field_open():
    metadata = {'description': '###'}
    canonicalize_metadata(metadata)
    assert metadata['description'] is None


# --- which text a source gives ------------------------------------------------

def _merge_screenscraper(synopsis):
    metadata = collections.defaultdict(lambda: None)
    metadata_merger.apply_screenscraper_to_metadata(
        metadata, {'synopsis': synopsis}, db_game_id=1, result={'filled_fields': []})
    return metadata['description']


def test_screenscraper_french_only_description_leaves_the_field_open():
    french = [{'langue': 'fr', 'text': 'Un jeu'}]
    assert not _merge_screenscraper(french)
    assert not scrape_screenscraper.parse_game_data({'synopsis': french})['description']


def test_screenscraper_english_description_is_taken():
    both = [{'langue': 'fr', 'text': 'Un jeu'}, {'langue': 'en', 'text': 'A game'}]
    assert _merge_screenscraper(both) == 'A game'
    assert scrape_screenscraper.parse_game_data({'synopsis': both})['description'] == 'A game'


def test_igdb_prefers_the_summary_over_the_story():
    metadata = collections.defaultdict(lambda: None)
    data = {'summary': 'What the game is', 'storyline': 'The plot'}
    metadata_merger.apply_igdb_to_metadata(metadata, data, 1, {'filled_fields': []})
    assert metadata['description'] == 'What the game is'


def test_igdb_story_is_used_when_there_is_no_summary():
    metadata = collections.defaultdict(lambda: None)
    metadata_merger.apply_igdb_to_metadata(metadata, {'storyline': 'The plot'}, 1, {'filled_fields': []})
    assert metadata['description'] == 'The plot'


def test_igdb_executable_names_are_not_alternate_titles():
    metadata = collections.defaultdict(lambda: None)
    metadata['title'] = 'Viking Child'
    data = {'alternative_names': [
        {'name': 'dosbox.exe', 'comment': 'Windows Executable'},
        {'name': 'VIKING.EXE'},
        {'name': 'viking', 'comment': 'Windows Executable'},
        {'name': 'Prophecy: The Viking Child', 'comment': 'Other'},
    ]}
    metadata_merger.apply_igdb_to_metadata(metadata, data, 1, {'filled_fields': []})
    assert [e['title'] for e in metadata['alternate_titles']] == ['Prophecy: The Viking Child']


def _rawg(monkeypatch, **record):
    monkeypatch.setattr(scrape_rawg, '_make_request',
                        lambda endpoint, params=None: {'id': 7, **record} if endpoint == 'games/7' else None)
    return scrape_rawg.get_game_details(7)


@pytest.mark.parametrize('name,clean', [
    ('Sonic the Hedgehog (1991)', 'Sonic the Hedgehog'),
    ('Descent 2 (1996)', 'Descent 2'),
    ('1943', '1943'),
    ('Game (Remake)', 'Game (Remake)'),
])
def test_rawg_title_loses_a_trailing_year(monkeypatch, name, clean):
    assert _rawg(monkeypatch, name=name)['name'] == clean


def test_rawg_alternate_names_only_from_a_one_console_record(monkeypatch):
    names = ['SEGA AGES: Sonic the Hedgehog']
    many = [{'platform': {'id': 1}}, {'platform': {'id': 2}}]
    one = [{'platform': {'id': 1}}]
    assert _rawg(monkeypatch, name='Sonic', platforms=many, alternative_names=names)['alternative_names'] == []
    assert _rawg(monkeypatch, name='Sonic', platforms=one, alternative_names=names)['alternative_names'] == names


def test_esde_keeps_a_company_named_in_digits():
    assert scrape_esde.resolve_publisher_developer('989', 'publisher') == '989'


def test_not_rated_is_no_esrb_rating():
    assert not metadata_normalizer.normalize_esrb_rating('NOT RATED')


def test_inference_is_told_the_system(monkeypatch):
    seen = {}
    monkeypatch.setattr(hybrid_scraper, 'infer_rating_from_content',
                        lambda game: seen.update(game) or None)
    hybrid_scraper._normalize_ratings({'title': 'Doom'}, {'filled_fields': []}, system_folder='nes')
    assert seen['system_folder'] == 'nes'


# --- regions ------------------------------------------------------------------

def _region(value):
    metadata = {'region': value}
    hybrid_scraper._normalize_region(metadata, {'filled_fields': []})
    return metadata['region']


@pytest.mark.parametrize('value,clean', [
    ('USA/Europe', 'USA'), ('Japan/USA', 'Japan'), ('USA, Europe', 'USA'),
    ('North America', 'USA'), ('Japan', 'Japan'),
    # Not offered in the default list, but true: stays, rather than becoming USA.
    ('France', 'France'),
])
def test_stored_region_is_one_value(value, clean):
    assert _region(value) == clean


@pytest.mark.parametrize('name,region', [
    ('Game (France).zip', 'France'), ('Game (Germany).zip', 'Germany'), ('Game (Spain).zip', 'Spain'),
    ('Game (Italy).zip', 'Italy'), ('Game (Korea).zip', 'Korea'), ('Game (China).zip', 'China'),
    ('Game (Brazil).zip', 'Brazil'), ('Game (Fr).zip', 'France'),
])
def test_file_name_regions_in_full(name, region):
    assert scrape_esde.extract_region_from_filename(name) == region


# --- stored rows --------------------------------------------------------------

@pytest.fixture
def stored():
    conn = sqlite3.connect(':memory:')
    conn.execute("""CREATE TABLE games (id INTEGER PRIMARY KEY, description TEXT, publisher TEXT,
        developer TEXT, alternate_titles TEXT, screenshots TEXT, esrb_rating TEXT, region TEXT,
        other_platforms TEXT)""")
    return conn


def _tidy(conn, **cols):
    conn.execute(f"INSERT INTO games ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                 list(cols.values()))
    migrations._load('030_tidy_stored_text').apply(conn)
    names = ', '.join(cols)
    return dict(zip(cols, conn.execute(f'SELECT {names} FROM games').fetchone()))


@pytest.mark.parametrize('field,before,after', [
    ('description', 'The &quot;hub&quot;\r\n###Plot', 'The "hub"\nPlot'),
    ('publisher', 'Sega', 'SEGA'),
    ('developer', 'Ubi Soft', 'Ubisoft'),
    ('screenshots', 'a.webp, b.webp', 'a.webp,b.webp'),
    ('esrb_rating', 'NOT RATED', None),
    ('esrb_rating', 'E', 'E'),
    ('region', 'USA/Europe', 'USA'),
    ('region', 'North America', 'USA'),
    ('region', 'France', 'France'),
    ('other_platforms', 'Super Nintendo Entertainment System, Commodore 64, Exclusive, SNES', 'SNES, C64, Exclusive'),
    ('other_platforms', 'PC, Made-Up Console', 'PC, Made-Up Console'),
])
def test_migration_tidies(stored, field, before, after):
    assert _tidy(stored, **{field: before})[field] == after


def test_migration_drops_executable_alternate_titles(stored):
    keep = {'title': 'Labyrinth', 'note': 'Working title', 'source': 'igdb'}
    titles = [{'title': 'dosbox.exe', 'note': 'Windows Executable', 'source': 'igdb'},
              {'title': 'viking', 'note': 'Windows Executable', 'source': 'igdb'}, keep]
    found = _tidy(stored, alternate_titles=json.dumps(titles))['alternate_titles']
    assert json.loads(found) == [keep]


def test_migration_leaves_unreadable_alternate_titles(stored):
    assert _tidy(stored, alternate_titles='not json')['alternate_titles'] == 'not json'


def test_migration_runs_on_a_database_with_no_games_table():
    migrations._load('030_tidy_stored_text').apply(sqlite3.connect(':memory:'))


def test_second_igdb_path_also_prefers_the_summary():
    assert "igdb_data.get('summary') or igdb_data.get('storyline'" in open(scrape_igdb.__file__, encoding='utf-8').read()
