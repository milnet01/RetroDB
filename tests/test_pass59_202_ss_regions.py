"""PASS-59-202: ScreenScraper media, titles and dates follow the game's region.

The region lists are the real orders from the Sonic 2 and Gran Turismo 4
replies: ScreenScraper lists regions alphabetically, and the first was taken.
No test here reaches ScreenScraper.
"""
import json
import sqlite3

import pytest

import config
from scraper import metadata_merger
from services import migrations

SONIC_BOXES = ['au', 'br', 'eu', 'jp', 'kr', 'ss', 'us']
SONIC_MANUALS = ['br', 'eu', 'jp', 'us']
GT4_BOXES = ['de', 'eu', 'fr', 'jp', 'kr', 'sp', 'us']


def _media(kind, regions, fmt='png'):
    return [{'type': kind, 'region': r, 'format': fmt,
             'url': f'https://ss.example/{kind}/{r}'} for r in regions]


def _meta(**over):
    keys = ('title', 'description', 'release_date', 'developer', 'publisher',
            'genre', 'players', 'esrb_rating', 'boxart', 'boxart_3d',
            'screenshots', 'fanart', 'video', 'manual', 'region')
    return {**{k: '' for k in keys}, **over}


@pytest.fixture(autouse=True)
def usa_first(monkeypatch):
    """The shipped default settings, whatever this machine has saved."""
    monkeypatch.setattr('services.version_groups.preferred_regions',
                        lambda: ['USA', 'World', 'Europe', 'Japan'])


@pytest.fixture
def fetched(monkeypatch):
    """Every URL a merge tries to download. Each try is refused, so nothing
    reaches the network; images and manuals share this first check."""
    urls = []

    def refuse(url):
        urls.append(url)
        return False, None, None

    def image(url, path, image_type, **_):
        urls.append(url)
        return False

    monkeypatch.setattr('services.ssrf.validate_outbound_url', refuse)
    monkeypatch.setattr(metadata_merger, '_download_and_finalize', image)
    return urls


def _apply(meta, record, **kw):
    metadata_merger.apply_screenscraper_to_metadata(
        meta, record, 1, {'filled_fields': []}, **kw)


# --- boxes and manuals ------------------------------------------------------

@pytest.mark.parametrize('kind, regions', [
    ('box-2D', SONIC_BOXES), ('box-2D', GT4_BOXES),
    ('box-3D', SONIC_BOXES), ('manuel', SONIC_MANUALS),
])
def test_usa_game_gets_the_usa_media(fetched, kind, regions):
    _apply(_meta(region='USA'), {'medias': _media(kind, regions)})
    assert fetched == [f'https://ss.example/{kind}/us']


@pytest.mark.parametrize('kind, regions', [
    ('box-2D', SONIC_BOXES), ('manuel', SONIC_MANUALS),
])
def test_japan_game_gets_the_japan_media(fetched, kind, regions):
    _apply(_meta(region='Japan'), {'medias': _media(kind, regions)})
    assert fetched == [f'https://ss.example/{kind}/jp']


def test_no_own_copy_falls_to_preferred_regions(fetched):
    _apply(_meta(region='Korea'), {'medias': _media('box-2D', ['au', 'eu', 'us'])})
    assert fetched == ['https://ss.example/box-2D/us']


def test_own_region_argument_beats_the_stored_region(fetched):
    # The stored region can be the AI's guess; the caller passes the file's.
    _apply(_meta(region='Europe'), {'medias': _media('box-2D', SONIC_BOXES)},
           own_region='Japan')
    assert fetched == ['https://ss.example/box-2D/jp']


def test_existing_media_is_still_never_replaced(fetched):
    _apply(_meta(region='USA', boxart='mine.webp', manual='mine.pdf'),
           {'medias': _media('box-2D', SONIC_BOXES) + _media('manuel', SONIC_MANUALS)})
    assert fetched == []


# --- titles and dates -------------------------------------------------------

NAMES = [{'region': 'jp', 'text': 'Rockman'}, {'region': 'us', 'text': 'Mega Man'}]
DATES = [{'region': 'br', 'text': '1992-12-01'}, {'region': 'jp', 'text': '1992-11-21'},
         {'region': 'us', 'text': '1992-11-24'}]


def test_japan_game_gets_its_own_title_and_date():
    meta = _meta(region='Japan')
    _apply(meta, {'noms': NAMES, 'dates': DATES})
    assert meta['title'] == 'Rockman'
    assert meta['release_date'] == '1992-11-21'


def test_game_with_no_region_gets_the_preferred_title_and_date():
    meta = _meta()
    _apply(meta, {'noms': NAMES, 'dates': DATES})
    assert meta['title'] == 'Mega Man'
    assert meta['release_date'] == '1992-11-24'


def test_description_stays_english_on_a_japan_game():
    meta = _meta(region='Japan')
    _apply(meta, {'synopsis': [{'langue': 'fr', 'text': 'Bonjour'},
                               {'langue': 'en', 'text': 'Hello'}]})
    assert meta['description'] == 'Hello'


# --- the one ordering helper ------------------------------------------------

@pytest.mark.parametrize('own, first', [
    ('USA', 'us'), ('Japan', 'jp'), ('Europe', 'eu'), ('World', 'wor'),
    ('usa', 'us'), ('USA/Europe', 'us'), ('Japan/USA', 'jp'), ('USA, Europe', 'us'),
    ('France', 'fr'), ('Germany', 'de'), ('Spain', 'sp'),
    ('', 'us'), (None, 'us'), ('Mars', 'us'),
])
def test_by_region_puts_the_own_region_first(own, first):
    from scraper.ss_regions import by_region
    items = [{'region': r} for r in ['de', 'eu', 'fr', 'jp', 'sp', 'ss', 'us', 'wor']]
    assert by_region(items, own)[0]['region'] == first


def test_europe_copy_prefers_world_to_another_language():
    """The Atari ST Spider-Man: a Europe copy, boxes only from Germany and
    the World. Europe means its general entry and the UK's, not every country."""
    from scraper.ss_regions import by_region
    items = [{'region': r} for r in ['de', 'fr', 'us', 'wor']]
    assert [i['region'] for i in by_region(items, 'Europe')] == ['us', 'wor', 'de', 'fr']
    assert by_region([{'region': 'de'}, {'region': 'uk'}], 'PAL')[0]['region'] == 'uk'


def test_by_region_ends_with_ss_then_the_rest_in_listed_order():
    from scraper.ss_regions import by_region
    items = [{'region': r} for r in ['kr', 'br', 'ss']]
    assert [i['region'] for i in by_region(items, 'USA')] == ['ss', 'kr', 'br']


def test_by_region_survives_odd_items():
    from scraper.ss_regions import by_region
    assert by_region(None) == []
    assert by_region([{'text': 'x'}, 'nope', {'region': None}]) == [{'text': 'x'}, {'region': None}]


@pytest.mark.parametrize('rom_path, stored, expected', [
    ('/r/Sonic (USA).zip', 'Europe', 'USA'),
    ('/r/Sonic.zip', 'Europe', 'Europe'),
    ('/r/Sonic.zip', None, None),
    (None, None, None),
])
def test_own_region_trusts_the_file_name_first(rom_path, stored, expected):
    from scraper.ss_regions import own_region
    assert own_region({'rom_path': rom_path, 'region': stored}) == expected


# --- the search list and the raw-reply path share the order -----------------

def test_search_result_prefers_the_same_regions():
    from scraper.scraper_manager import ScraperManager
    assert ScraperManager._pick_ss_region(
        [{'region': 'eu', 'text': 'E'}, {'region': 'us', 'text': 'U'}]) == ('US', 'U')
    # A game dated only in Japan used to get no region at all.
    assert ScraperManager._pick_ss_region([{'region': 'jp', 'text': 'J'}]) == ('JP', 'J')
    assert ScraperManager._pick_ss_region([]) == (None, None)


def test_rom_lookup_path_follows_the_game_region():
    from scraper.scrape_screenscraper import parse_game_data
    jeu = {'noms': NAMES, 'dates': DATES, 'medias': _media('box-2D', SONIC_BOXES)}
    parsed = parse_game_data(jeu, 'Japan')
    assert parsed['title'] == 'Rockman'
    assert parsed['release_date'] == '1992-11-21'
    assert parsed['media']['boxart_front'].endswith('/jp')


def test_search_scores_against_every_regional_name():
    from scraper.match_scorer import calculate_ss_score
    us_only = {'name': 'Mega Man', 'alternate_titles': []}
    with_jp = {'name': 'Mega Man', 'alternate_titles': [{'title': 'Rockman', 'region': 'jp'}]}
    assert calculate_ss_score(with_jp, 'Rockman') > calculate_ss_score(us_only, 'Rockman')
    assert with_jp['title_score'] == calculate_ss_score({'name': 'Rockman'}, 'Rockman')


# --- video ------------------------------------------------------------------

VIDEOS = _media('video', ['']) + _media('video-normalized', [''], fmt='mp4')


def test_smaller_video_is_tried_first_then_the_larger(fetched):
    _apply(_meta(), {'medias': VIDEOS})
    assert fetched == ['https://ss.example/video-normalized/',
                       'https://ss.example/video/']


def test_larger_video_is_not_fetched_when_the_smaller_arrives(monkeypatch):
    urls = []

    def arrive(url, *a, **k):
        urls.append(url)
        return True

    monkeypatch.setattr(metadata_merger, 'download_ss_media', arrive)
    meta = _meta()
    _apply(meta, {'medias': VIDEOS})
    assert urls == ['https://ss.example/video-normalized/']
    assert meta['video'] == '1_ss_video.mp4'


# --- the repair job ---------------------------------------------------------

ROM = '/roms/md/Sonic (USA).zip'
RECORD = {'id': 77, 'medias': (_media('box-2D', SONIC_BOXES)
                               + _media('box-3D', ['us'])
                               + _media('manuel', SONIC_MANUALS, fmt='pdf'))}


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A migrated database and media folders, with one ScreenScraper game."""
    path = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(path)
    migrations.apply_pending(conn)
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'Mega Drive', 'megadrive')")
    conn.execute("INSERT INTO games (id, system_id, title, rom_path, screenscraper_id, boxart, "
                 "boxart_3d, manual) VALUES (1, 1, 'Sonic', ?, 77, '1_ss_boxart.webp', "
                 "'1_ss_boxart3d.webp', '1_ss_manual.pdf')", (ROM,))
    conn.commit()
    conn.close()
    images = tmp_path / 'images'
    for sub, name in (('boxart', '1_ss_boxart.webp'), ('boxart', '1_ss_boxart-md.webp'),
                      ('boxart_3d', '1_ss_boxart3d.webp'), ('manuals', '1_ss_manual.pdf')):
        (images / sub).mkdir(parents=True, exist_ok=True)
        (images / sub / name).write_bytes(b'old')
    monkeypatch.setattr(config, 'DB_PATH', path)
    monkeypatch.setattr(config, 'IMAGE_PATH', str(images))
    monkeypatch.setattr(config, 'STATIC_PATH', str(tmp_path))

    def row():
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        found = dict(c.execute("SELECT * FROM games WHERE id = 1").fetchone())
        c.close()
        return found

    return row, images


def _run_job(monkeypatch, reply, image_ok=True, manual_bytes=b'%PDF-1.4'):
    """Run the job's worker on this thread with a canned lookup reply."""
    from services.jobs import ss_region_repair as mod
    searches, downloads = [], []

    def lookup(ss_id, *a, **k):
        searches.append(ss_id)
        return reply

    def image(url, path, image_type, **_):
        downloads.append(url)
        if image_ok:
            with open(path, 'wb') as f:
                f.write(b'new')
        return image_ok

    def manual(url, path, **_):
        downloads.append(url)
        with open(path, 'wb') as f:
            f.write(manual_bytes)
        return True

    monkeypatch.setattr(mod, 'get_game_by_id', lookup)
    monkeypatch.setattr(mod, '_download_and_finalize', image)
    monkeypatch.setattr(mod, 'download_ss_media', manual)
    monkeypatch.setattr(mod, 'preferred_image_extension', lambda _t, ext: '.webp')
    job = mod.SsRegionRepairJob()
    job.running = True
    job._worker({'screenscraper_username': 'u', 'screenscraper_password': 'p'})
    return job, searches, downloads


def test_repair_swaps_a_wrong_region_box_and_manual(library, monkeypatch):
    row, images = library
    job, _, downloads = _run_job(monkeypatch, RECORD)
    # 3D lists only the USA, so the stored copy is already right.
    assert downloads == ['https://ss.example/box-2D/us', 'https://ss.example/manuel/us']
    game = row()
    assert game['boxart'] == '1_ss_boxart_us.webp'
    assert game['manual'] == '1_ss_manual_us.pdf'
    assert game['boxart_3d'] == '1_ss_boxart3d.webp'
    assert (images / 'boxart' / '1_ss_boxart_us.webp').read_bytes() == b'new'
    assert not (images / 'boxart' / '1_ss_boxart.webp').exists()
    assert not (images / 'boxart' / '1_ss_boxart-md.webp').exists()
    assert not (images / 'manuals' / '1_ss_manual.pdf').exists()
    assert (images / 'boxart_3d' / '1_ss_boxart3d.webp').exists()
    assert job.get_status()['replaced'] == 2
    assert job.get_status()['completed'] is True


def test_repair_keeps_the_old_file_when_the_download_fails(library, monkeypatch):
    row, images = library
    job, _, _ = _run_job(monkeypatch, RECORD, image_ok=False)
    assert row()['boxart'] == '1_ss_boxart.webp'
    assert (images / 'boxart' / '1_ss_boxart.webp').read_bytes() == b'old'
    assert job.get_status()['failed'] == 1


def test_repair_refuses_a_manual_that_is_not_a_document(library, monkeypatch):
    row, images = library
    job, _, _ = _run_job(monkeypatch, RECORD, manual_bytes=b'NOMEDIA')
    assert row()['manual'] == '1_ss_manual.pdf'
    assert (images / 'manuals' / '1_ss_manual.pdf').read_bytes() == b'old'
    assert not (images / 'manuals' / '1_ss_manual_us.pdf').exists()
    assert job.get_status()['failed'] == 1


def test_repair_leaves_a_game_alone_when_the_reply_lacks_its_id(library, monkeypatch):
    row, images = library
    job, _, downloads = _run_job(monkeypatch, {'id': 76, 'medias': RECORD['medias']})
    assert downloads == []
    assert row()['boxart'] == '1_ss_boxart.webp'
    assert job.get_status()['no_match'] == 1


def test_repair_skips_a_game_it_already_repaired(library, monkeypatch):
    row, _ = library
    _run_job(monkeypatch, RECORD)
    # 3D keeps its first-listed name, but the game is settled: no second lookup.
    _, searches, downloads = _run_job(monkeypatch, RECORD)
    assert (searches, downloads) == ([], [])
    assert row()['boxart'] == '1_ss_boxart_us.webp'
    assert row()['ss_region_checked'] == 1


def _holding_swapped_box(code, images):
    """Game 1 as a Europe copy holding a box an earlier run swapped in."""
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("UPDATE games SET rom_path = '/roms/md/Sonic.zip', region = 'Europe', "
                 "boxart = ?, boxart_3d = NULL, manual = NULL", (f'1_ss_boxart_{code}.webp',))
    conn.commit()
    conn.close()
    (images / 'boxart' / f'1_ss_boxart_{code}.webp').write_bytes(b'old')


def test_repair_swaps_a_box_it_swapped_into_another_language(library, monkeypatch):
    row, images = library
    _holding_swapped_box('de', images)
    reply = {'id': 77, 'medias': _media('box-2D', ['de', 'wor'])}
    _, _, downloads = _run_job(monkeypatch, reply)
    assert downloads == ['https://ss.example/box-2D/wor']
    assert row()['boxart'] == '1_ss_boxart_wor.webp'
    assert not (images / 'boxart' / '1_ss_boxart_de.webp').exists()
    assert row()['ss_region_checked'] == 1


def test_repair_does_not_ask_about_a_swapped_box_the_order_still_ranks(library, monkeypatch):
    """Only a region the order no longer ranks can be wrong now."""
    row, images = library
    _holding_swapped_box('eu', images)
    reply = {'id': 77, 'medias': _media('box-2D', ['de', 'eu', 'wor'])}
    _, searches, downloads = _run_job(monkeypatch, reply)
    assert (searches, downloads) == ([], [])
    assert row()['boxart'] == '1_ss_boxart_eu.webp'


def test_a_german_reader_keeps_the_german_box(library, monkeypatch):
    row, images = library
    _holding_swapped_box('de', images)
    monkeypatch.setattr('scraper.ss_regions.reading_languages', lambda: ['de'])
    _, searches, _ = _run_job(monkeypatch, {'id': 77, 'medias': _media('box-2D', ['de', 'wor'])})
    assert searches == []
    assert row()['boxart'] == '1_ss_boxart_de.webp'


def test_repair_asks_again_after_a_failed_download(library, monkeypatch):
    row, _ = library
    _run_job(monkeypatch, RECORD, image_ok=False)
    assert row()['ss_region_checked'] == 0
    _, searches, _ = _run_job(monkeypatch, RECORD)
    assert searches == [77]
    assert row()['ss_region_checked'] == 1


def test_repair_asks_again_about_a_game_not_found(library, monkeypatch):
    row, _ = library
    _run_job(monkeypatch, None)
    assert row()['ss_region_checked'] == 0
    _, searches, _ = _run_job(monkeypatch, None)
    assert searches == [77]


def _scraped_at(stamp, first_run=None, order='readable'):
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("UPDATE games SET scrape_history = ?",
                 (json.dumps([{'timestamp': stamp, 'primary_source': 'screenscraper'}]),))
    if first_run:
        params = json.dumps({'total': 1, 'order': order} if order else {'total': 1})
        conn.execute("INSERT INTO job_queue (job_type, status, created_at, updated_at, params) "
                     "VALUES ('ss_region_repair', 'dismissed', ?, ?, ?)",
                     (first_run, first_run, params))
    conn.commit()
    conn.close()


def test_repair_settles_a_game_first_scraped_after_its_first_run(library, monkeypatch):
    row, _ = library
    _scraped_at('2026-11-05T10:00:00', first_run='2026-11-01T19:13:32+00:00')
    _, searches, downloads = _run_job(monkeypatch, RECORD)
    assert (searches, downloads) == ([], [])
    assert row()['boxart'] == '1_ss_boxart.webp'
    assert row()['ss_region_checked'] == 1


def test_a_run_from_before_the_language_order_proves_nothing(library, monkeypatch):
    """Scrapes after such a run could still take a box in another language."""
    _scraped_at('2026-11-05T10:00:00', first_run='2026-11-01T19:13:32+00:00', order=None)
    _, searches, _ = _run_job(monkeypatch, RECORD)
    assert searches == [77]


def test_repair_asks_about_a_game_scraped_before_its_first_run(library, monkeypatch):
    row, _ = library
    _scraped_at('2026-07-04T15:01:07', first_run='2026-11-01T19:13:32+00:00')
    _, searches, _ = _run_job(monkeypatch, RECORD)
    assert searches == [77]
    assert row()['boxart'] == '1_ss_boxart_us.webp'


def test_repair_with_no_earlier_run_asks_about_every_scraped_game(library, monkeypatch):
    _scraped_at('2026-11-05T10:00:00')
    _, searches, _ = _run_job(monkeypatch, RECORD)
    assert searches == [77]


def test_repair_ignores_media_from_other_sources(library, monkeypatch):
    row, images = library
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("UPDATE games SET boxart = '1_igdb.webp', boxart_3d = NULL, manual = NULL")
    conn.commit()
    conn.close()
    _, searches, _ = _run_job(monkeypatch, RECORD)
    assert searches == []
    assert row()['boxart'] == '1_igdb.webp'


def _more_games(count):
    conn = sqlite3.connect(config.DB_PATH)
    for i in range(2, count + 2):
        conn.execute("INSERT INTO games (id, system_id, title, rom_path, screenscraper_id, boxart) "
                     "VALUES (?, 1, ?, ?, 77, ?)",
                     (i, f'G{i}', f'/r/G{i}.zip', f'{i}_ss_boxart.webp'))
    conn.commit()
    conn.close()


def test_repair_stops_when_the_days_limit_is_reached(library, monkeypatch):
    from scraper import service_limits
    from services.jobs import ss_region_repair as mod
    _more_games(5)
    real_stopped = service_limits.stopped
    calls = []

    def stopped_after_two(source):
        calls.append(source)
        if len(calls) == 3:
            service_limits.stop(source, 60)
        return real_stopped(source)

    monkeypatch.setattr(service_limits, 'stopped', stopped_after_two)
    job, searches, _ = _run_job(monkeypatch, None)
    assert len(searches) == 2
    assert job.get_status()['no_match'] == 1


def test_repair_carries_on_past_games_that_are_not_found(library, monkeypatch):
    _more_games(30)
    _, searches, _ = _run_job(monkeypatch, None)
    assert len(searches) == 31


def test_repair_leaves_an_unmapped_system_alone(library, monkeypatch):
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("UPDATE systems SET folder = 'not-a-system'")
    conn.commit()
    conn.close()
    _, searches, _ = _run_job(monkeypatch, RECORD)
    assert searches == []


def test_start_refuses_without_an_account(monkeypatch):
    from services.jobs import ss_region_repair as mod
    monkeypatch.setattr(mod, 'load_scraper_settings', lambda: {'api_keys': {}})
    assert mod.SsRegionRepairJob().start() == {'success': False, 'error': 'no_account'}


def test_start_route_words_the_refusal(admin_test_client, monkeypatch):
    from services.jobs import ss_region_repair as mod
    monkeypatch.setattr(mod, 'load_scraper_settings', lambda: {'api_keys': {}})
    client, csrf = admin_test_client()
    reply = client.post('/api/maintenance/ss-region-repair/start', json={},
                        headers={'X-CSRF-Token': csrf})
    assert reply.status_code == 400
    assert 'ScreenScraper account' in reply.get_json()['error']


def test_status_route_has_what_the_card_reads(admin_test_client):
    client, _csrf = admin_test_client()
    status = client.get('/api/maintenance/ss-region-repair/status').get_json()
    for key in ('running', 'completed', 'cancelled', 'paused', 'current', 'total', 'replaced',
                'no_match', 'failed', 'service_stops', 'error'):
        assert key in status


def test_changed_list_names_each_swapped_file(library, monkeypatch):
    from services.jobs.ss_region_repair import swapped_games
    assert swapped_games() == []
    _run_job(monkeypatch, RECORD)
    changed = swapped_games()
    assert [g['id'] for g in changed] == [1]
    # The 3D box kept its first-listed file, so it is not listed as changed.
    assert changed[0]['changes'] == [('boxart', 'us'), ('manual', 'us')]
    assert changed[0]['system_name'] == 'Mega Drive'


def test_pause_holds_the_run_until_resumed(library, monkeypatch):
    import threading
    import time
    from services.jobs import ss_region_repair as mod
    _more_games(3)
    searches = []
    monkeypatch.setattr(mod, 'get_game_by_id', lambda ss_id, *a, **k: searches.append(ss_id))
    job = mod.SsRegionRepairJob()
    job.running = True
    assert job.pause() == {'success': True}
    assert job.get_status()['paused'] is True
    worker = threading.Thread(target=job._worker, args=({'screenscraper_username': 'u', 'screenscraper_password': 'p'},))
    worker.start()
    time.sleep(0.3)
    assert searches == []
    assert job.resume() == {'success': True}
    worker.join(5)
    assert len(searches) == 4
    assert job.get_status()['paused'] is False


def test_stop_ends_a_paused_run(library, monkeypatch):
    import threading
    from services.jobs import ss_region_repair as mod
    searches = []
    monkeypatch.setattr(mod, 'get_game_by_id', lambda ss_id, *a, **k: searches.append(ss_id))
    job = mod.SsRegionRepairJob()
    job.running = True
    job.pause()
    worker = threading.Thread(target=job._worker, args=({'screenscraper_username': 'u', 'screenscraper_password': 'p'},))
    worker.start()
    assert job.cancel() == {'success': True}
    worker.join(5)
    assert not worker.is_alive()
    assert searches == []
    assert job.get_status()['cancelled'] is True


def test_pause_and_resume_refuse_when_nothing_runs():
    from services.jobs import ss_region_repair as mod
    job = mod.SsRegionRepairJob()
    assert job.pause()['success'] is False
    assert job.resume()['success'] is False


def test_box_regions_page_opens(admin_test_client):
    client, _csrf = admin_test_client()
    page = client.get('/tools/box-regions')
    assert page.status_code == 200
    assert b'regionFixStatus' in page.data


# --- whose languages count ---------------------------------------------------

def test_reading_languages_come_from_people_who_scrape(tmp_path, monkeypatch):
    from scraper.ss_regions import reading_languages
    from services.database_init import ensure_user_tables
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'users.db'))
    ensure_user_tables()                        # seeds an admin reading 'en'
    assert reading_languages() == ['en']
    conn = sqlite3.connect(config.DB_PATH)
    for uid, role, ticked, screen in ((2, 'editor', 'de,fr', 'en'),
                                      (3, 'editor', '', 'pt_BR'),
                                      (4, 'player', 'ja', 'ja')):
        conn.execute("INSERT INTO users (id, username, password_hash, role) VALUES (?, ?, 'x', ?)",
                     (uid, f'u{uid}', role))
        conn.execute("INSERT INTO user_settings (user_id, read_languages, locale_preference) "
                     "VALUES (?, ?, ?)", (uid, ticked, screen))
    conn.commit()
    conn.close()
    # Ticked languages replace the screen language; none ticked means it.
    # A player cannot scrape, so Japanese does not count.
    assert sorted(reading_languages()) == ['de', 'en', 'fr', 'pt']


def test_reading_languages_without_user_tables_is_english(tmp_path, monkeypatch):
    from scraper.ss_regions import reading_languages
    monkeypatch.setattr(config, 'DB_PATH', str(tmp_path / 'empty.db'))
    assert reading_languages() == ['en']
