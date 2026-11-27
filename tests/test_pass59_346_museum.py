"""PASS-59-346: two museum faults.

The image and content buttons call editor-only APIs, so only an editor or an
admin sees them; and the type filter's "Engine" choice finds engine systems.
"""
import os
import sqlite3

import pytest

SYSTEM_ID = 934601
CTRL_ID = 934602

# Each calls an editor-only API in routes/museum.py. Matched as the button's
# attribute: every page also lists all handler names in base.html.
SYSTEM_PAGE_ACTIONS = ('data-on-click="generateContent"', 'data-on-click="fetchAllControllerImages"',
                       'data-on-click="fetchControllerImage"', 'data-on-click="uploadControllerImage"',
                       'id="ctrlUpload')
LANDING_ACTIONS = ('data-on-click="startBulkGenerate"', 'data-on-click="cancelBulkGenerate"')


@pytest.fixture
def museum_rows():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT OR REPLACE INTO systems (id, name, folder) VALUES (?, 'P346 System', 'p346sys')",
                 (SYSTEM_ID,))
    conn.execute("INSERT OR REPLACE INTO controllers (id, system_id, name) VALUES (?, ?, 'P346 Pad')",
                 (CTRL_ID, SYSTEM_ID))
    conn.execute("INSERT INTO system_controllers (system_id, controller_id) VALUES (?, ?)",
                 (SYSTEM_ID, CTRL_ID))
    conn.commit()
    conn.close()
    yield
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("DELETE FROM system_controllers WHERE system_id = ?", (SYSTEM_ID,))
    conn.execute("DELETE FROM controllers WHERE id = ?", (CTRL_ID,))
    conn.execute("DELETE FROM systems WHERE id = ?", (SYSTEM_ID,))
    conn.commit()
    conn.close()


def _pages(admin_test_client, role):
    client, _csrf = admin_test_client(user={'id': 1, 'username': f'{role}-stub', 'role': role})
    system = client.get(f'/museum/{SYSTEM_ID}')
    landing = client.get('/museum')
    assert system.status_code == 200 and landing.status_code == 200
    return system.get_data(as_text=True), landing.get_data(as_text=True)


@pytest.mark.parametrize('role', ['viewer', 'player'])
def test_museum_hides_editor_actions_from_other_roles(museum_rows, admin_test_client, role):
    system, landing = _pages(admin_test_client, role)
    assert 'P346 Pad' in system
    for marker in SYSTEM_PAGE_ACTIONS:
        assert marker not in system, marker
    for marker in LANDING_ACTIONS:
        assert marker not in landing, marker


@pytest.mark.parametrize('role', ['editor', 'admin'])
def test_museum_shows_editor_actions_to_editors(museum_rows, admin_test_client, role):
    system, landing = _pages(admin_test_client, role)
    for marker in SYSTEM_PAGE_ACTIONS:
        assert marker in system, marker
    for marker in LANDING_ACTIONS:
        assert marker in landing, marker


@pytest.mark.parametrize('folder', ['scummvm', 'pico8', 'ports'])
def test_engine_systems_have_the_engine_type(folder):
    from routes.museum import _get_system_type
    assert _get_system_type(folder) == 'Engine'
