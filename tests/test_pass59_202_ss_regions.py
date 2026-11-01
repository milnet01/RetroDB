"""PASS-59-202: ScreenScraper media, titles and dates follow the game's region.

The region lists are the real orders from the Sonic 2 and Gran Turismo 4
replies: ScreenScraper lists regions alphabetically, and the first was taken.
No test here reaches ScreenScraper.
"""
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
    """Run the job's worker on this thread with a canned search reply."""
    from services.jobs import ss_region_repair as mod
    searches, downloads = [], []

    def search(title, folder, *a, **k):
        searches.append(title)
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

    monkeypatch.setattr(mod, 'search_game', search)
    monkeypatch.setattr(mod, '_download_and_finalize', image)
    monkeypatch.setattr(mod, 'download_ss_media', manual)
    monkeypatch.setattr(mod, 'PACE_SECONDS', 0)
    monkeypatch.setattr(mod, 'preferred_image_extension', lambda _t, ext: '.webp')
    job = mod.SsRegionRepairJob()
    job.running = True
    job._worker({'screenscraper_username': 'u', 'screenscraper_password': 'p'})
    return job, searches, downloads


def test_repair_swaps_a_wrong_region_box_and_manual(library, monkeypatch):
    row, images = library
    job, _, downloads = _run_job(monkeypatch, [{'id': 76}, RECORD])
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
    job, _, _ = _run_job(monkeypatch, [RECORD], image_ok=False)
    assert row()['boxart'] == '1_ss_boxart.webp'
    assert (images / 'boxart' / '1_ss_boxart.webp').read_bytes() == b'old'
    assert job.get_status()['failed'] == 1


def test_repair_refuses_a_manual_that_is_not_a_document(library, monkeypatch):
    row, images = library
    job, _, _ = _run_job(monkeypatch, [RECORD], manual_bytes=b'NOMEDIA')
    assert row()['manual'] == '1_ss_manual.pdf'
    assert (images / 'manuals' / '1_ss_manual.pdf').read_bytes() == b'old'
    assert not (images / 'manuals' / '1_ss_manual_us.pdf').exists()
    assert job.get_status()['failed'] == 1


def test_repair_leaves_a_game_alone_when_the_reply_lacks_its_id(library, monkeypatch):
    row, images = library
    job, _, downloads = _run_job(monkeypatch, [{'id': 76, 'medias': RECORD['medias']}])
    assert downloads == []
    assert row()['boxart'] == '1_ss_boxart.webp'
    assert job.get_status()['no_match'] == 1


def test_repair_skips_a_game_it_already_repaired(library, monkeypatch):
    row, _ = library
    _run_job(monkeypatch, [RECORD])
    # 3D still holds its first-listed name, so the game is checked once more.
    _, _, downloads = _run_job(monkeypatch, [RECORD])
    assert downloads == []
    assert row()['boxart'] == '1_ss_boxart_us.webp'


def test_repair_ignores_media_from_other_sources(library, monkeypatch):
    row, images = library
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("UPDATE games SET boxart = '1_igdb.webp', boxart_3d = NULL, manual = NULL")
    conn.commit()
    conn.close()
    _, searches, _ = _run_job(monkeypatch, [RECORD])
    assert searches == []
    assert row()['boxart'] == '1_igdb.webp'


def test_repair_stops_when_replies_dry_up(library, monkeypatch):
    from services.jobs import ss_region_repair as mod
    conn = sqlite3.connect(config.DB_PATH)
    for i in range(2, mod.MAX_SILENT_IN_A_ROW + 5):
        conn.execute("INSERT INTO games (id, system_id, title, rom_path, screenscraper_id, boxart) "
                     "VALUES (?, 1, ?, ?, 77, ?)",
                     (i, f'G{i}', f'/r/G{i}.zip', f'{i}_ss_boxart.webp'))
    conn.commit()
    conn.close()
    job, searches, _ = _run_job(monkeypatch, None)
    assert len(searches) == mod.MAX_SILENT_IN_A_ROW
    assert job.get_status()['stopped_no_reply'] is True


def test_repair_leaves_an_unmapped_system_alone(library, monkeypatch):
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("UPDATE systems SET folder = 'not-a-system'")
    conn.commit()
    conn.close()
    _, searches, _ = _run_job(monkeypatch, [RECORD])
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
    for key in ('running', 'completed', 'cancelled', 'current', 'total', 'replaced',
                'no_match', 'failed', 'stopped_no_reply', 'error'):
        assert key in status
