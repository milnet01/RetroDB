"""A system an import or migration 045 creates or repairs gets its name, logo and type.

The Xbox import created `xboxseriesx` as "XBOXSERIESX" with no logo or type:
its folder had no mapped name, it looked for the logo only under IMAGE_PATH
(the bundled logos live under STATIC_PATH), and it never set a type.
"""
import sqlite3

import pytest

import config
from services import game_utils
from tests._versions_util import vdb  # noqa: F401  (a fixture)
from tests.test_migration_015 import _load

ADMIN = {'id': 1, 'username': 'admin-stub', 'role': 'admin'}
FOLDER = 'p59sysdef'


@pytest.fixture
def logo_roots(tmp_path, monkeypatch):
    """A bundled logo for FOLDER under STATIC_PATH, and an empty IMAGE_PATH."""
    bundled = tmp_path / 'static' / 'images' / 'systems'
    bundled.mkdir(parents=True)
    (bundled / f'{FOLDER}.png').write_bytes(b'png')
    (tmp_path / 'images' / 'systems').mkdir(parents=True)
    monkeypatch.setattr(config, 'STATIC_PATH', str(tmp_path / 'static'))
    monkeypatch.setattr(config, 'IMAGE_PATH', str(tmp_path / 'images'))
    monkeypatch.setitem(config.SYSTEM_NAME_MAP, FOLDER, 'Maker Console')
    monkeypatch.setitem(game_utils.SYSTEM_TYPE_MAP, FOLDER, 'Console')
    return tmp_path


def _created_row(vdb, create):  # noqa: F811
    import app as app_module
    from flask import g
    try:
        with app_module.app.test_request_context():
            g.user = ADMIN
            create(FOLDER)
        return tuple(vdb.conn.execute(
            "SELECT name, logo, system_type FROM systems WHERE folder = ?", (FOLDER,)).fetchone())
    finally:
        vdb.conn.execute("DELETE FROM systems WHERE folder = ?", (FOLDER,))
        vdb.conn.commit()


def test_platform_import_creates_a_named_typed_system_with_its_logo(vdb, logo_roots):  # noqa: F811
    import routes.platform_import as pi
    assert _created_row(vdb, pi._ensure_system_exists) == ('Maker Console', f'{FOLDER}.png', 'Console')


def test_clz_import_creates_a_named_typed_system_with_its_logo(vdb, logo_roots):  # noqa: F811
    import routes.clz_import as clz
    assert _created_row(vdb, clz._create_system) == ('Maker Console', f'{FOLDER}.png', 'Console')


def test_an_imported_logo_wins_over_the_bundled_one(logo_roots):
    (logo_roots / 'images' / 'systems' / f'{FOLDER}.webp').write_bytes(b'webp')
    assert game_utils.system_defaults(FOLDER)[1] == f'{FOLDER}.webp'


# --- Migration 045 --------------------------------------------------------------

def _systems_db():
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE systems (id INTEGER PRIMARY KEY, name TEXT NOT NULL, "
                 "folder TEXT NOT NULL UNIQUE, logo TEXT, system_type TEXT)")
    conn.executemany("INSERT INTO systems (name, folder, logo, system_type) VALUES (?, ?, ?, ?)", [
        (FOLDER.upper(), FOLDER, None, None),          # made by an import before the fix
        ('My Name', 'p59other', 'mine.png', 'Engine'),  # set by hand: left alone
        ('P59UNMAPPED', 'p59unmapped', None, ''),       # no mapped name, no logo, no type
    ])
    return conn


def test_migration_045_repairs_a_system_an_import_made(logo_roots):
    conn = _systems_db()
    migration = _load('045_imported_system_defaults')
    migration.apply(conn)
    migration.apply(conn)                      # runs twice without harm
    rows = conn.execute("SELECT folder, name, logo, system_type FROM systems ORDER BY id").fetchall()
    assert rows == [
        (FOLDER, 'Maker Console', f'{FOLDER}.png', 'Console'),
        ('p59other', 'My Name', 'mine.png', 'Engine'),
        ('p59unmapped', 'P59UNMAPPED', None, ''),
    ]
