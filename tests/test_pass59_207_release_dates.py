"""PASS-59-207: a release date stays as exact as its source, and belongs to this
console and region. IGDB and ScreenScraper also fill the regional dates.

No test here reaches a service; the replies are canned. The IGDB entries follow
a live reply of 2026-11-02: `date_format` 0 is a full date, 1 a month, 2 a year.
"""
import json
import sqlite3
from datetime import datetime, timezone

import pytest

import config
from scraper import scrape_ai, scrape_esde, scrape_igdb
from scraper.metadata_merger import (
    apply_igdb_to_metadata,
    apply_rawg_to_metadata,
    apply_screenscraper_to_metadata,
    apply_tgdb_to_metadata,
)
from services import game_cleanup, migrations
from services.release_dates import (
    igdb_regional_dates,
    merge_release_dates,
    pick_release_date,
    source_date,
    year_gap_with_own_region,
)

PS2, NES, FAMICOM, ZX = 8, 18, 99, 26
EU, NA, JP = 1, 2, 5


def _ts(day):
    return int(datetime.fromisoformat(day).replace(tzinfo=timezone.utc).timestamp())


def _full(day, platform, region):
    return {'date': _ts(day), 'y': int(day[:4]), 'm': int(day[5:7]), 'date_format': 0,
            'platform': platform, 'release_region': region}


GT3 = [_full('2001-07-10', PS2, NA), _full('2001-04-28', PS2, JP),
       _full('2001-07-20', PS2, EU)]
# IGDB's own reply for OutRun: year only, with a made-up month and timestamp.
OUTRUN_ZX = [{'date': 567907200, 'y': 1987, 'm': 12, 'date_format': 2,
              'platform': ZX, 'release_region': EU}]


def _meta(**over):
    keys = ('title', 'description', 'release_date', 'release_dates', 'developer',
            'publisher', 'genre', 'players', 'modes', 'esrb_rating', 'pegi_rating',
            'boxart', 'boxart_3d', 'screenshots', 'fanart', 'video', 'manual', 'region',
            'alternate_titles', 'franchise', 'similar_games', 'perspective',
            'critic_score', 'critic_score_count', 'user_score', 'user_score_count',
            'playtime_estimate', 'cero_rating', 'usk_rating', 'acb_rating', 'fpb_rating',
            'grac_rating', 'classind_rating', 'dimension', 'game_structure')
    return {**{k: '' for k in keys}, **over}


def _result():
    return {'filled_fields': [], 'sources_used': []}


@pytest.fixture(autouse=True)
def usa_first(monkeypatch):
    """The shipped default settings, whatever this machine has saved."""
    monkeypatch.setattr('services.version_groups.preferred_regions',
                        lambda: ['USA', 'World', 'Europe', 'Japan'])


# --- what a source really knows ---------------------------------------------

@pytest.mark.parametrize('given, kept', [
    ('1991-06-23', '1991-06-23'),
    ('1991-06-23T00:00:00Z', '1991-06-23'),
    ('1991/06/23', '1991-06-23'),
    ('1991', '1991'),
    ('1991-06', '1991-06'),
    ('1987-01-01', '1987'),         # one day stands for "some time that year"
    ('1987-03-01', '1987-03-01'),   # only ES-DE pads months
    ('1970-01-01', None),           # a zero date, not a release
    ('Unknown', None),
    ('June 1991', None),
    ('1991-13-40', None),
    ('', None),
    (None, None),
])
def test_source_date(given, kept):
    assert source_date(given) == kept


@pytest.mark.parametrize('given, kept', [
    ('1982-01-01', '1982'),
    ('1983-06-01', '1983-06'),
    ('1982-12-06', '1982-12-06'),
    ('1983-01', '1983-01'),
])
def test_source_date_when_months_are_padded(given, kept):
    assert source_date(given, padded_months=True) == kept


# --- IGDB -------------------------------------------------------------------

def test_igdb_year_only_stays_a_year():
    """A year-only date was stored as 31 December."""
    assert igdb_regional_dates(OUTRUN_ZX, ZX) == {'EU': '1987'}


def test_igdb_month_only_stays_a_month():
    entry = {'date': _ts('1993-02-28'), 'y': 1993, 'm': 2, 'date_format': 1,
             'platform': NES, 'release_region': NA}
    assert igdb_regional_dates([entry], NES) == {'NA': '1993-02'}


@pytest.mark.parametrize('fmt, kept', [(3, {'NA': '1993'}), (6, {'NA': '1993'}), (7, {})])
def test_igdb_quarters_are_a_year_and_tbd_is_nothing(fmt, kept):
    entry = {'y': 1993, 'm': 3, 'date_format': fmt, 'platform': NES, 'release_region': NA}
    assert igdb_regional_dates([entry], NES) == kept


def test_igdb_keeps_only_this_console():
    other = _full('1989-01-15', 13, NA)
    assert igdb_regional_dates([other, _full('1993-02-05', NES, NA)], NES) == {'NA': '1993-02-05'}


def test_igdb_counts_famicom_as_the_nes():
    """IGDB files a Japanese NES release under the Famicom."""
    found = igdb_regional_dates([_full('1991-03-21', FAMICOM, JP), _full('1993-02-05', NES, NA)], NES)
    assert found == {'NA': '1993-02-05', 'JP': '1991-03-21'}


def test_igdb_with_no_known_console_uses_every_entry_earliest_first():
    found = igdb_regional_dates([_full('1993-02-05', NES, NA), _full('1989-01-15', 13, NA)], None)
    assert found == {'NA': '1989-01-15'}


def test_igdb_ignores_unknown_regions_and_bad_entries():
    assert igdb_regional_dates([{'y': 1990, 'date_format': 2, 'platform': NES}, 'x'], NES) == {}
    assert igdb_regional_dates(None, NES) == {}


def test_igdb_usa_game_gets_the_usa_date():
    """It used to get the Japanese date, the earliest for any region."""
    meta = _meta(region='USA')
    apply_igdb_to_metadata(meta, {'first_release_date': _ts('2001-04-28'), 'release_dates': GT3},
                           1, _result(), platform_id=PS2)
    assert meta['release_date'] == '2001-07-10'


def test_igdb_own_region_argument_beats_the_stored_region():
    meta = _meta(region='USA')
    apply_igdb_to_metadata(meta, {'release_dates': GT3}, 1, _result(),
                           platform_id=PS2, own_region='Japan')
    assert meta['release_date'] == '2001-04-28'


def test_igdb_fills_the_regional_dates():
    meta, result = _meta(region='USA'), _result()
    apply_igdb_to_metadata(meta, {'release_dates': GT3}, 1, result, platform_id=PS2)
    assert json.loads(meta['release_dates']) == {
        'NA': '2001-07-10', 'EU': '2001-07-20', 'JP': '2001-04-28'}
    assert 'release_dates (IGDB)' in result['filled_fields']


def test_igdb_first_date_alone_is_not_this_console_or_exact():
    """first_release_date may be another console's, and hides how exact it is."""
    meta, result = _meta(region='USA'), _result()
    apply_igdb_to_metadata(meta, {'first_release_date': 567907200}, 1, result, platform_id=ZX)
    assert meta['release_date'] == ''
    assert not [f for f in result['filled_fields'] if f.startswith('release_date')]


def test_igdb_other_console_only_gives_no_date():
    meta = _meta(region='USA')
    apply_igdb_to_metadata(meta, {'release_dates': [_full('1989-01-15', 13, NA)]}, 1, _result(),
                           platform_id=NES)
    assert meta['release_date'] == ''


def test_igdb_details_ask_for_the_dates(monkeypatch):
    bodies = []
    monkeypatch.setattr(scrape_igdb, 'igdb_auth', lambda: 't')
    monkeypatch.setattr(scrape_igdb, 'igdb_request', lambda e, b, t: bodies.append(b) or [{}])
    scrape_igdb.fetch_game_details(1)
    for field in ('date', 'y', 'm', 'date_format', 'platform', 'release_region'):
        assert f'release_dates.{field}' in bodies[0]


def test_extended_igdb_fetch_asks_for_the_dates(monkeypatch):
    from scraper import hybrid_scraper
    bodies = []
    monkeypatch.setattr(hybrid_scraper, 'igdb_auth', lambda: 't')
    monkeypatch.setattr(hybrid_scraper, 'igdb_request', lambda e, b, t: bodies.append(b) or [{}])
    hybrid_scraper.fetch_igdb_extended(1)
    assert 'release_dates.date_format' in bodies[0]
    assert 'release_dates.release_region' in bodies[0]


# --- choosing one date ------------------------------------------------------

@pytest.mark.parametrize('dates, own, picked', [
    ({'JP': '1991', 'NA': '1992'}, 'Japan', ('1991', True)),
    ({'JP': '1991', 'NA': '1992'}, 'USA/Europe', ('1992', True)),
    ({'WW': '1995'}, 'Japan', ('1995', True)),
    ({'NA': '1992', 'BR': '1990'}, 'Japan', ('1992', False)),   # the preferred region
    ({'BR': '1993', 'KR': '1990'}, 'Japan', ('1990', False)),   # then the earliest
    ({'EU': '1994'}, 'Germany', ('1994', True)),
    ({'NA': '1992'}, None, ('1992', False)),
    ({}, 'USA', (None, False)),
])
def test_pick_release_date(dates, own, picked):
    assert pick_release_date(dates, own) == picked


# --- a fuller date for the same year ----------------------------------------

def test_own_region_date_fills_out_a_year():
    meta = _meta(region='USA', release_date='2001')
    apply_igdb_to_metadata(meta, {'release_dates': GT3}, 1, _result(), platform_id=PS2)
    assert meta['release_date'] == '2001-07-10'


def test_another_regions_date_never_fills_out_a_year():
    meta = _meta(region='Korea', release_date='2001')
    apply_igdb_to_metadata(meta, {'release_dates': GT3}, 1, _result(), platform_id=PS2)
    assert meta['release_date'] == '2001'


def test_a_full_date_or_another_year_is_never_replaced():
    for stored in ('2001-07-01', '1999'):
        meta = _meta(region='USA', release_date=stored)
        apply_igdb_to_metadata(meta, {'release_dates': GT3}, 1, _result(), platform_id=PS2)
        assert meta['release_date'] == stored


# --- ScreenScraper ----------------------------------------------------------

SS_DATES = [{'region': 'jp', 'text': '1992-11-21'}, {'region': 'us', 'text': '1992-11-24'},
            {'region': 'de', 'text': '1993'}, {'region': 'eu', 'text': '1993-03-01'},
            {'region': 'ss', 'text': '1990'}]


def test_screenscraper_fills_the_regional_dates():
    meta, result = _meta(region='USA'), _result()
    apply_screenscraper_to_metadata(meta, {'dates': SS_DATES}, 1, result)
    assert json.loads(meta['release_dates']) == {
        'NA': '1992-11-24', 'EU': '1993-03-01', 'JP': '1992-11-21'}
    assert 'release_dates (ScreenScraper)' in result['filled_fields']
    assert meta['release_date'] == '1992-11-24'


def test_screenscraper_padded_new_year_becomes_a_year():
    meta = _meta(region='USA')
    apply_screenscraper_to_metadata(meta, {'dates': [{'region': 'us', 'text': '1992-01-01'}]}, 1, _result())
    assert meta['release_date'] == '1992'


def test_screenscraper_generic_date_does_not_fill_out_a_year():
    meta = _meta(region='USA', release_date='1990')
    apply_screenscraper_to_metadata(meta, {'dates': [{'region': 'ss', 'text': '1990-05-05'}]}, 1, _result())
    assert meta['release_date'] == '1990'


def test_screenscraper_own_date_fills_out_a_year():
    meta = _meta(region='USA', release_date='1992')
    apply_screenscraper_to_metadata(meta, {'dates': SS_DATES}, 1, _result())
    assert meta['release_date'] == '1992-11-24'


# --- regional dates stay fill-only ------------------------------------------

def test_stored_regional_dates_are_kept_and_gaps_filled():
    assert json.loads(merge_release_dates('{"NA":"1984"}', {'NA': '1990-01-02', 'JP': '1983-07-15'})) \
        == {'NA': '1984', 'JP': '1983-07-15'}


def test_nothing_new_means_nothing_to_write():
    assert merge_release_dates('{"NA":"1984"}', {'NA': '1990'}) is None
    assert merge_release_dates(None, {}) is None


def test_two_sources_share_the_regional_dates():
    meta = _meta(region='USA')
    apply_screenscraper_to_metadata(meta, {'dates': [{'region': 'jp', 'text': '2001-04-28'}]}, 1, _result())
    apply_igdb_to_metadata(meta, {'release_dates': [_full('2001-07-10', PS2, NA), _full('2001-04-29', PS2, JP)]},
                           1, _result(), platform_id=PS2)
    assert json.loads(meta['release_dates']) == {'NA': '2001-07-10', 'JP': '2001-04-28'}


# --- RAWG -------------------------------------------------------------------

RAWG_PLATFORMS = [{'platform': {'id': 4}, 'released_at': '2024-12-13'},
                  {'platform': {'id': 167}, 'released_at': '1989-09-01'}]


def test_rawg_uses_this_consoles_date():
    meta = _meta()
    apply_rawg_to_metadata(meta, {'release_date': '1989-09-01', 'platforms': RAWG_PLATFORMS},
                           1, _result(), platform_id=4)
    assert meta['release_date'] == '2024-12-13'


def test_rawg_falls_back_to_the_records_date():
    meta = _meta()
    apply_rawg_to_metadata(meta, {'release_date': '1989-09-01', 'platforms': [{'platform': {'id': 4}}]},
                           1, _result(), platform_id=4)
    assert meta['release_date'] == '1989-09-01'


def test_rawg_never_fills_out_a_year():
    """RAWG has one record for all regions, so its day may be another region's."""
    meta = _meta(release_date='1989')
    apply_rawg_to_metadata(meta, {'release_date': '1989-09-01'}, 1, _result())
    assert meta['release_date'] == '1989'


def test_rawg_padded_new_year_becomes_a_year():
    meta = _meta()
    apply_rawg_to_metadata(meta, {'release_date': '1989-01-01'}, 1, _result())
    assert meta['release_date'] == '1989'


# --- TheGamesDB -------------------------------------------------------------

@pytest.mark.parametrize('sent, kept', [
    ('1987-01-01', '1987'), ('1970-01-01', ''), ('1991-06-23', '1991-06-23'),
])
def test_tgdb_dates(sent, kept):
    meta = _meta()
    apply_tgdb_to_metadata(meta, {'release_date': sent}, 1, _result())
    assert meta['release_date'] == kept


# --- ES-DE ------------------------------------------------------------------

@pytest.mark.parametrize('raw, kept', [
    ('19820101T000000', '1982'),
    ('19830601T000000', '1983-06'),
    ('19821206T000000', '1982-12-06'),
    ('19700101T000000', ''),
    ('not-a-date', ''),
    ('', ''),
])
def test_esde_date(raw, kept):
    assert scrape_esde.esde_date(raw) == kept


# --- the AI -----------------------------------------------------------------

@pytest.mark.parametrize('value, kept', [
    ('Unknown', ''), ('June 1991', ''), ('1991-06-23', '1991-06-23'),
    ('1991-06', '1991-06'), ('1991-01-01', '1991'),
])
def test_ai_date_is_checked(value, kept):
    assert scrape_ai._validate_field('release_date', value) == kept


def test_ai_is_told_the_games_region():
    prompt = scrape_ai._build_prompt('Mega Man', 'NES', ['release_date'], date_region='Japan')
    assert 'in the Japan region' in prompt
    assert 'YYYY-MM' in prompt


def test_ai_prompt_with_no_region_names_none():
    assert 'region' not in scrape_ai._build_prompt('Mega Man', 'NES', ['release_date']).split(
        '"release_date"')[1].splitlines()[0]


# --- what disagrees is logged, not corrected --------------------------------

@pytest.mark.parametrize('date, regional, own, flagged', [
    ('1983', '{"NA":"2002-04"}', 'USA', True),
    ('1983', '{"NA":"1984-02"}', 'USA', False),     # one year apart is common
    ('1983', '{"JP":"2002-04"}', 'USA', False),     # not this copy's region
    ('', '{"NA":"2002-04"}', 'USA', False),
    ('1983', None, 'USA', False),
])
def test_year_gap_with_own_region(date, regional, own, flagged):
    assert year_gap_with_own_region(date, regional, own) is flagged


# --- the ROM Tools card -----------------------------------------------------

@pytest.fixture
def library(tmp_path, monkeypatch):
    path = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(path)
    migrations.apply_pending(conn)
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'Sega Saturn', 'saturn')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, 'DB_PATH', path)

    def add(game_id, date, source=None):
        history = json.dumps([{'fields_filled': [f'release_date ({source})']}]) if source else None
        c = sqlite3.connect(path)
        c.execute("INSERT INTO games (id, system_id, title, rom_path, release_date, scrape_history) "
                  "VALUES (?, 1, 'Game', ?, ?, ?)", (game_id, f'/r/{game_id}.iso', date, history))
        c.commit()
        c.close()

    def date_of(game_id):
        c = sqlite3.connect(path)
        row = c.execute("SELECT release_date FROM games WHERE id = ?", (game_id,)).fetchone()
        c.close()
        return row[0]

    add.date_of = date_of
    return add


@pytest.mark.parametrize('stored, source, wanted', [
    ('1987-12-31', 'IGDB', '1987'),
    ('1987-06-30', 'IGDB', '1987-06-30'),
    ('1987-01-01', 'IGDB', '1987-01-01'),       # IGDB had no reason to pad 1 January
    ('1982-01-01', 'ES-DE', '1982'),
    ('1983-06-01', 'ES-DE', '1983-06'),
    ('1982-12-06', 'ES-DE', '1982-12-06'),
    ('1987-01-01', 'TGDB', '1987'),
    ('1987-01-01', 'RAWG', '1987'),
    ('1987-01-01', 'ScreenScraper', '1987'),
    ('1987-01-01', 'AI', '1987'),
    ('1987-06-01', 'RAWG', '1987-06-01'),       # only ES-DE pads months
    ('1985', 'ScreenScraper', '1985'),
    ('1987-01-01', None, '1987-01-01'),         # no scrape filled it
    ('1987-12-31', None, '1987-12-31'),
    ('1970-01-01', 'TGDB', None),
    ('1970-01-01', None, None),
])
def test_tidying_a_stored_date(library, stored, source, wanted):
    library(1, stored, source)
    assert game_cleanup.count_release_date_changes() == (0 if wanted == stored else 1)
    assert game_cleanup.fix_release_dates() == (0 if wanted == stored else 1)
    assert library.date_of(1) == wanted
    assert game_cleanup.count_release_date_changes() == 0


def test_the_newest_scrape_credit_decides(library):
    library(1, '1987-12-31', 'IGDB')
    c = sqlite3.connect(config.DB_PATH)
    c.execute("UPDATE games SET scrape_history = ? WHERE id = 1", (json.dumps([
        {'fields_filled': ['release_date (IGDB)']},
        {'fields_filled': ['release_date (RAWG)']},
    ]),))
    c.commit()
    c.close()
    game_cleanup.fix_release_dates()
    assert library.date_of(1) == '1987-12-31'


def test_a_date_changed_since_the_search_is_left_alone(library, monkeypatch):
    library(1, '1987-01-01', 'RAWG')
    monkeypatch.setattr(game_cleanup, '_release_date_changes',
                        lambda: [(1, '1999-01-01', '1999')])
    assert game_cleanup.fix_release_dates() == 0
    assert library.date_of(1) == '1987-01-01'
