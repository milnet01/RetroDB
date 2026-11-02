"""PASS-59-205: ES-DE as a fallback goes through the normal merge.

Runs the real scrape against a throwaway ES-DE folder and library. The source
after ES-DE is a stand-in, so no test reaches a network.
"""
import os
import sqlite3

import pytest
from PIL import Image

import config
from scraper import hybrid_scraper, image_dedup, scrape_esde
from services import migrations


def _picture(path, flip=False):
    """A 64x64 picture; `flip` gives one that does not look the same."""
    img = Image.new('RGB', (64, 64))
    for x in range(64):
        for y in range(64):
            level = (63 - x if flip else x) * 4
            img.putpixel((x, y), (level, 255 - level, (x * y) % 256))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path)


def _file(path, content=b'media'):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as f:
        f.write(content)


class Library:
    def __init__(self, tmp_path):
        self.db = str(tmp_path / 'roms.db')
        self.images = str(tmp_path / 'images')
        self.static = str(tmp_path / 'static')
        self.esde = str(tmp_path / 'ES-DE')
        self.media = os.path.join(self.esde, 'downloaded_media', 'atari2600')

    def gamelist(self, *rows):
        body = ''.join(
            '<game><path>./{}</path><name>{}</name><developer>{}</developer>'
            '<publisher>{}</publisher><players>{}</players></game>'.format(*row)
            for row in rows)
        path = os.path.join(self.esde, 'gamelists', 'atari2600', 'gamelist.xml')
        _file(path, f'<gameList>{body}</gameList>'.encode())

    def add_game(self, rom='Fatal Run (USA).zip', **columns):
        columns = {'id': 1, 'system_id': 1, 'title': 'Fatal Run',
                   'rom_path': f'/roms/atari2600/{rom}', **columns}
        conn = sqlite3.connect(self.db)
        conn.execute(
            f"INSERT INTO games ({', '.join(columns)}) "
            f"VALUES ({', '.join('?' * len(columns))})", list(columns.values()))
        conn.commit()
        conn.close()

    def row(self):
        conn = sqlite3.connect(self.db)
        conn.row_factory = sqlite3.Row
        found = dict(conn.execute("SELECT * FROM games WHERE id = 1").fetchone())
        conn.close()
        return found

    def image(self, folder, name):
        return os.path.join(self.images, folder, name)


@pytest.fixture
def library(tmp_path, monkeypatch):
    lib = Library(tmp_path)
    conn = sqlite3.connect(lib.db)
    migrations.apply_pending(conn)
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'Atari 2600', 'atari2600')")
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, 'DB_PATH', lib.db)
    monkeypatch.setattr('scraper.base_scraper.DB_PATH', lib.db)
    for module in (hybrid_scraper, scrape_esde, image_dedup):
        monkeypatch.setattr(module, 'IMAGE_PATH', lib.images)
    for module in (hybrid_scraper, scrape_esde):
        monkeypatch.setattr(module, 'STATIC_PATH', lib.static)
    monkeypatch.setattr(scrape_esde, '_get_esde_gamelists_path',
                        lambda: os.path.join(lib.esde, 'gamelists'))
    monkeypatch.setattr(scrape_esde, '_get_esde_media_path',
                        lambda: os.path.join(lib.esde, 'downloaded_media'))
    monkeypatch.setenv('HOME', str(tmp_path))
    # Copies stay as they are: the real one upscales on the graphics card.
    monkeypatch.setattr('services.image_utils.standardize_downloaded_image', lambda *a, **k: None)
    return lib


@pytest.fixture
def later_source(monkeypatch):
    """Runs after ES-DE in the order and fills what is still empty, as RAWG does."""
    monkeypatch.setattr(hybrid_scraper, '_fallback_order',
                        lambda *a, **k: ['esde', 'rawg'])
    monkeypatch.setattr(hybrid_scraper, 'load_scraper_settings',
                        lambda: {'enabled': {}, 'api_keys': {}}, raising=False)
    monkeypatch.setitem(hybrid_scraper._FALLBACK_FETCHERS, 'rawg', lambda lookup: {'any': 1})

    def fill(metadata, data, db_game_id, result, fill_only=False, **_):
        for field, value in (('developer', 'Later Source'), ('fanart', 'later_fanart.png')):
            if not metadata[field]:
                metadata[field] = value
    monkeypatch.setattr(hybrid_scraper, 'apply_rawg_to_metadata', fill)


def _scrape(primary='none', primary_id=None, force=False):
    result = hybrid_scraper.apply_hybrid_metadata(
        1, primary, primary_id, 'atari2600', fill_gaps=True, force_overwrite=force)
    assert result.get('success', True) is not False, result
    return result


FATAL_RUN = ('Fatal Run (USA).zip', 'Fatal Run', 'Sculptured', 'Telegames', '1-2')


def test_fallback_text_is_kept_over_a_later_source(library, later_source):
    library.gamelist(FATAL_RUN)
    library.add_game()

    result = _scrape()

    row = library.row()
    assert row['developer'] == 'Sculptured'
    assert row['publisher'] == 'Telegames'
    assert row['players'] == 2
    assert 'developer (ES-DE)' in result['filled_fields']


def test_fallback_keeps_a_value_already_in_the_row(library, later_source):
    library.gamelist(FATAL_RUN)
    library.add_game(developer='Hand Set')

    _scrape()

    assert library.row()['developer'] == 'Hand Set'


def test_fallback_screenshots_are_appended_not_dropped(library, later_source):
    library.gamelist(FATAL_RUN)
    _picture(library.image('screenshots', 'old.png'))
    _picture(os.path.join(library.media, 'screenshots', 'Fatal Run (USA).png'), flip=True)
    library.add_game(screenshots='old.png')

    _scrape()

    listed = [s.strip() for s in library.row()['screenshots'].split(',')]
    assert listed == ['old.png', '1_esde_ss.png']


def test_a_screenshot_that_looks_the_same_is_not_added(library, later_source):
    library.gamelist(FATAL_RUN)
    _picture(library.image('screenshots', 'old.png'))
    _picture(os.path.join(library.media, 'screenshots', 'Fatal Run (USA).png'))
    library.add_game(screenshots='old.png')

    _scrape()

    assert library.row()['screenshots'] == 'old.png'
    assert not os.path.exists(library.image('screenshots', '1_esde_ss.png'))


def test_fallback_cover_stops_a_later_source_taking_the_field(library, later_source):
    library.gamelist(FATAL_RUN)
    _file(os.path.join(library.media, 'fanart', 'Fatal Run (USA).png'))
    library.add_game()

    _scrape()

    assert library.row()['fanart'] == '1_esde_fanart.png'


@pytest.mark.parametrize('field,folder,source,copy', [
    ('fanart', 'fanart', 'fanart/Fatal Run (USA).png', 'images/fanart/1_esde_fanart.png'),
    ('video', 'videos', 'videos/Fatal Run (USA).mp4', 'static/videos/1_esde.mp4'),
    ('manual', 'manuals', 'manuals/Fatal Run (USA).pdf', 'images/manuals/1_esde.pdf'),
])
def test_media_the_game_already_has_is_not_copied(
        library, later_source, tmp_path, field, folder, source, copy):
    library.gamelist(FATAL_RUN)
    _file(os.path.join(library.media, source))
    kept = os.path.join(library.static, 'videos', 'mine.mp4') if field == 'video' \
        else library.image(folder, 'mine.mp4')
    _file(kept)
    library.add_game(**{field: 'mine.mp4'})

    _scrape()

    assert library.row()[field] == 'mine.mp4'
    assert not os.path.exists(tmp_path / copy)


def test_full_rescrape_does_not_delete_a_box_it_just_downloaded(
        library, later_source, monkeypatch):
    """An earlier source reuses the row's file name; ES-DE must leave that file."""
    library.gamelist(FATAL_RUN)
    fresh = library.image('boxart', '1_ss_boxart.webp')
    _file(fresh)
    _file(os.path.join(library.media, 'covers', 'Fatal Run (USA).png'))
    library.add_game(boxart='1_ss_boxart.webp')
    monkeypatch.setattr(hybrid_scraper, '_fallback_order',
                        lambda *a, **k: ['rawg', 'esde'])

    def fill(metadata, data, db_game_id, result, fill_only=False, **_):
        metadata['boxart'] = '1_ss_boxart.webp'
    monkeypatch.setattr(hybrid_scraper, 'apply_rawg_to_metadata', fill)

    _scrape(force=True)

    assert os.path.exists(fresh)
    assert library.row()['boxart'] == '1_ss_boxart.webp'


def test_full_rescrape_with_esde_first_lets_another_source_replace_old_media(
        library, later_source):
    library.gamelist(FATAL_RUN)
    _file(library.image('fanart', 'old_fanart.png'))
    library.add_game(fanart='old_fanart.png')

    _scrape('esde', './Fatal Run (USA).zip', force=True)

    assert library.row()['fanart'] == 'later_fanart.png'


def test_primary_esde_still_fills_text_and_media(library, later_source):
    library.gamelist(FATAL_RUN)
    _file(os.path.join(library.media, 'covers', 'Fatal Run (USA).png'))
    library.add_game()

    result = _scrape('esde', './Fatal Run (USA).zip')

    row = library.row()
    assert row['developer'] == 'Sculptured'
    assert row['players'] == 2
    assert row['boxart'] == '1_esde_covers.png'
    assert 'ES-DE' in result['sources_used']
    assert 'boxart (ES-DE)' in result['filled_fields']


def test_fallback_uses_the_row_for_this_rom_not_the_first_with_that_name(
        library, later_source):
    library.gamelist(
        ('Cabal (1989) (Ocean).zip', 'Cabal', 'Ocean', 'Ocean', '1'),
        ('Cabal (1990) (Capcom).zip', 'Cabal', 'Capcom', 'Capcom', '1'),
    )
    library.add_game(rom='Cabal (1990) (Capcom).zip', title='Cabal')

    _scrape()

    assert library.row()['developer'] == 'Capcom'


def test_a_title_match_still_works_without_a_row_for_the_rom(library, later_source):
    library.gamelist(('Other Name.zip', 'Fatal Run', 'Sculptured', 'Telegames', '1'))
    library.add_game()

    _scrape()

    assert library.row()['developer'] == 'Sculptured'


def test_a_title_match_brings_the_media_of_the_row_it_chose(library, later_source):
    library.gamelist(('Other Name.zip', 'Fatal Run', 'Sculptured', 'Telegames', '1'))
    _file(os.path.join(library.media, 'covers', 'Other Name.png'))
    library.add_game()

    _scrape()

    assert library.row()['boxart'] == '1_esde_covers.png'


def test_a_folder_rom_finds_media_named_with_its_whole_folder_name(library, later_source):
    rom = 'Guitar Hero 5 (USA).PS3'
    library.gamelist((rom, 'Guitar Hero 5', 'Neversoft', 'Activision', '4'))
    _file(os.path.join(library.media, 'covers', f'{rom}.png'))
    library.add_game(rom=rom, title='Guitar Hero 5')

    _scrape()

    assert library.row()['boxart'] == '1_esde_covers.png'


def test_the_direct_apply_does_not_replace_media_either(library):
    library.gamelist(FATAL_RUN)
    _file(os.path.join(library.media, 'videos', 'Fatal Run (USA).mp4'))
    library.add_game(video='mine.mp4')

    assert scrape_esde.apply_esde_metadata(1, {'name': 'Fatal Run'}, 'atari2600') is True

    assert library.row()['video'] == 'mine.mp4'
    assert not os.path.exists(os.path.join(library.static, 'videos', '1_esde.mp4'))


def _theme(library, relative):
    _file(os.path.join(library.esde, 'themes', relative))


def test_an_unrelated_theme_picture_does_not_become_a_system_logo(library):
    _theme(library, 'art/background_gbstyle.png')
    _theme(library, 'nes-collection/wallpaper.png')

    assert scrape_esde.import_system_logos() == 0


def test_a_logo_named_for_its_system_is_imported_with_its_real_extension(library):
    _theme(library, 'art/nes.jpg')

    assert scrape_esde.import_system_logos() == 1
    assert os.path.exists(library.image('systems', 'nes.jpg'))
    assert not os.path.exists(library.image('systems', 'nes.png'))


def test_a_scrape_gives_stored_words_the_canonical_names(library, later_source):
    """PASS-59-206: the conversion after the merge reaches what older scrapes stored."""
    library.gamelist(FATAL_RUN)
    library.add_game(genre='Racing, Arcade, Racing TPV', perspective='Side view')

    _scrape()

    row = library.row()
    assert row['genre'] == 'Racing'
    assert row['perspective'] == 'Side-Scroller'
