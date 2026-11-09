"""PASS-59-266: one answer to which kind a system is.

The ROM naming check used its own folder lists, which disagreed with the
Systems page: `mac` was checked as a console (Region tag) and a type set on
the Systems page was ignored.
"""
import sqlite3

import pytest

import config
from services import game_utils, migrations


@pytest.fixture
def systems(tmp_path, monkeypatch):
    path = str(tmp_path / 'roms.db')
    conn = sqlite3.connect(path)
    migrations.apply_pending(conn)
    conn.commit()
    conn.close()
    monkeypatch.setattr(config, 'DB_PATH', path)

    def add(folder, system_type=None):
        c = sqlite3.connect(path)
        c.execute("INSERT INTO systems (name, folder, system_type) VALUES (?, ?, ?)",
                  (folder, folder, system_type))
        c.commit()
        c.close()

    return add


@pytest.mark.parametrize('folder, expected', [
    ('mac', 'computer'), ('zxnext', 'computer'), ('adam', 'computer'),
    ('thomson', 'computer'), ('3ds', 'handheld'), ('vita', 'handheld'),
    ('virtualboy', 'handheld'), ('snes', 'console'), ('pico8', 'engine'),
    ('mame', 'console'), ('snes_eu', 'console'), ('nowhere', 'console'),
])
def test_folder_table_answers_when_nothing_is_stored(systems, folder, expected):
    assert game_utils.get_system_type(folder) == expected


def test_type_set_on_the_systems_page_wins(systems):
    systems('mysteryfolder', 'Computer')
    systems('gb', 'Console')
    assert game_utils.get_system_type('mysteryfolder') == 'computer'
    assert game_utils.get_system_type('gb') == 'console'


def test_arcade_or_unknown_stored_type_falls_back(systems):
    systems('mac', 'Arcade')
    systems('psp', 'Unknown')
    assert game_utils.get_system_type('mac') == 'computer'
    assert game_utils.get_system_type('psp') == 'handheld'


def test_systems_page_detects_from_the_same_table(systems):
    systems('mac')
    systems('psvita')
    systems('snes_eu')
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    from routes.systems import update_system_types
    update_system_types(conn.cursor())
    conn.commit()
    stored = dict(conn.execute("SELECT folder, system_type FROM systems").fetchall())
    conn.close()
    assert stored == {'mac': 'Computer', 'psvita': 'Handheld', 'snes_eu': 'Console'}
