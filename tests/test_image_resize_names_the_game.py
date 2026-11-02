"""The Image Resize toast names the game and system of the file it is working on."""
import sqlite3

import pytest

from services import migrations
from services.jobs import image_resize


@pytest.fixture
def library(tmp_path, monkeypatch):
    path = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(path)
    migrations.apply_pending(conn)
    conn.execute("INSERT INTO systems (id, name, folder) VALUES (1, 'Sega Mega Drive', 'megadrive')")
    conn.execute("INSERT INTO games (id, system_id, title, rom_path, boxart, boxart_3d, screenshots) "
                 "VALUES (1, 1, 'Altered Beast', '/r/a.zip', 'box.webp', NULL, 'a.webp, b.webp')")
    conn.commit()
    conn.close()
    monkeypatch.setattr('config.DB_PATH', path)
    monkeypatch.setattr('services.database.DB_PATH', path, raising=False)


def test_each_image_of_a_game_names_it(library):
    owners = image_resize._media_owners()
    for name in ('box.webp', 'a.webp', 'b.webp'):
        assert owners[name] == ('Altered Beast', 'Sega Mega Drive')
    assert 'orphan.webp' not in owners


def test_a_failed_read_does_not_stop_the_job(monkeypatch):
    def broken():
        raise sqlite3.OperationalError('no database')

    monkeypatch.setattr('services.database.get_db_with_context', broken)
    assert image_resize._media_owners() == {}


def test_status_reports_the_game_and_system():
    job = image_resize.ImageResizeJob()
    job.current_game, job.current_system = 'Altered Beast', 'Sega Mega Drive'
    status = job.get_status()
    assert status['current_game'] == 'Altered Beast'
    assert status['current_system'] == 'Sega Mega Drive'
