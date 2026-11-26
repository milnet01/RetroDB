"""PASS-59-345: turnable 3D consoles and controllers in the museum.

Pins three things: every model the list names ships in the form
static/js/hardware-model.js reads; a model is matched to the right system and
to controllers by whole part numbers; and the museum page offers each model
with its credit, loading the viewer only where there is one.
"""
import json
import os
import shutil
import sqlite3
import struct

import pytest

import config
from services import hardware_models

# The repository's own files: conftest points config.STATIC_PATH at a
# throwaway folder, so the fixture below copies the list in for the service.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODEL_DIR = os.path.join(REPO_ROOT, 'static', 'models', 'hardware')
LISTED = json.load(open(os.path.join(MODEL_DIR, 'models.json'), encoding='utf-8'))
SYSTEM_ID = 926501
CTRL_IDS = (926502, 926503)


def _glb_json(path):
    with open(path, 'rb') as f:
        head = f.read(20)
        magic, version, _length, json_length, chunk_type = struct.unpack('<IIIII', head)
        assert (magic, version, chunk_type) == (0x46546C67, 2, 0x4E4F534A), path
        return json.loads(f.read(json_length))


def test_every_listed_model_ships_and_every_file_is_listed():
    files = {n[:-4] for n in os.listdir(MODEL_DIR) if n.endswith('.glb')}
    assert files == set(LISTED)


@pytest.mark.parametrize('key', sorted(LISTED))
def test_model_is_in_the_form_the_viewer_reads(key):
    g = _glb_json(os.path.join(MODEL_DIR, f'{key}.glb'))
    assert set(g.get('extensionsRequired', [])) <= {'EXT_texture_webp'}
    assert not any(b.get('uri') for b in g.get('buffers', []))
    assert not any('sparse' in a or a.get('normalized') for a in g['accessors'])
    for mesh in g['meshes']:
        for p in mesh['primitives']:
            assert p.get('mode', 4) == 4
            for name in p['attributes']:
                assert g['accessors'][p['attributes'][name]]['componentType'] == 5126, (key, name)


@pytest.mark.parametrize('key', sorted(LISTED))
def test_model_carries_its_credit(key):
    entry = LISTED[key]
    assert entry.get('systems') or entry.get('controllers')
    if not entry.get('ours'):
        assert entry['title'] and entry['author']
        assert entry['source'].startswith('https://sketchfab.com/3d-models/')


@pytest.fixture(autouse=True)
def shipped_list():
    """The service reads models.json under config.STATIC_PATH."""
    target = os.path.join(config.STATIC_PATH, 'models', 'hardware')
    os.makedirs(target, exist_ok=True)
    shutil.copy(os.path.join(MODEL_DIR, 'models.json'), target)
    hardware_models._models.cache_clear()
    yield
    hardware_models._models.cache_clear()


@pytest.mark.parametrize('folder, key', [
    ('psx', 'ps1'), ('gc', 'gamecube'), ('megadrive', 'megadrive'),
    ('genesis', None),          # the model reads MEGA DRIVE
    ('sfc', None),
])
def test_console_model_by_system_folder(folder, key):
    model = hardware_models.for_system(folder)
    assert (model and model['key']) == key


@pytest.mark.parametrize('name, key', [
    ('DualShock (SCPH-1200)', 'pad-dualshock'),
    ('DualShock 2 (SCPH-10010)', None),
    ('3-Button Control Pad (1650 / 1653 / MK-1650)', 'pad-megadrive'),
    ('6-Button Control Pad (1470 / 1650 / MK-1470)', None),
    ('Sega Control Pad (3020 / 3021 / MK-1391 / MK-1470)', 'pad-mastersystem'),
    ('Joystick (CX10 / CX40)', 'pad-2600'),
    ('Wireless Joystick (CX42)', None),
    ('NES Zapper (NES-005)', 'zapper'),
    ('Control Pad (HSS-0101 / MK-80100 / MK-80116)', 'pad-saturn'),
    ('', None),
])
def test_controller_model_by_whole_part_number(name, key):
    model = hardware_models.for_controller(name)
    assert (model and model['key']) == key


@pytest.fixture
def museum_rows():
    import app  # noqa: F401 — builds the throwaway schema
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("INSERT OR REPLACE INTO systems (id, name, folder) VALUES (?, 'P345 PlayStation', 'psx')",
                 (SYSTEM_ID,))
    for cid, name in zip(CTRL_IDS, ('DualShock (SCPH-1200)', 'Mouse (SCPH-1030)')):
        conn.execute("INSERT OR REPLACE INTO controllers (id, system_id, name) VALUES (?, ?, ?)",
                     (cid, SYSTEM_ID, name))
        conn.execute("INSERT INTO system_controllers (system_id, controller_id) VALUES (?, ?)",
                     (SYSTEM_ID, cid))
    conn.commit()
    conn.close()
    yield
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("DELETE FROM system_controllers WHERE system_id = ?", (SYSTEM_ID,))
    conn.execute("DELETE FROM controllers WHERE id IN (?, ?)", CTRL_IDS)
    conn.execute("DELETE FROM systems WHERE id = ?", (SYSTEM_ID,))
    conn.commit()
    conn.close()


def test_museum_page_offers_each_model_with_its_credit(museum_rows, admin_test_client):
    client, _csrf = admin_test_client()
    html = client.get(f'/museum/{SYSTEM_ID}').get_data(as_text=True)
    assert html.count('class="btn btn-sm btn-secondary museum-model-button"') == 1
    assert html.count('class="btn btn-xs btn-secondary museum-model-button"') == 1   # the mouse has none
    assert 'data-model-url="/static/models/hardware/ps1.glb"' in html
    assert 'data-model-url="/static/models/hardware/pad-dualshock.glb"' in html
    assert html.count('class="museum-model-credit"') == 2
    assert 'by Ceki' in html and 'by valdes1302' in html
    assert 'All logos and trademarks belong to the companies that own them.' in html
    assert 'js/hardware-model.js' in html


def test_museum_page_without_a_model_loads_no_viewer(museum_rows, admin_test_client):
    conn = sqlite3.connect(os.environ['RETRODB_DB_PATH'])
    conn.execute("UPDATE systems SET folder = 'p345none' WHERE id = ?", (SYSTEM_ID,))
    conn.execute("UPDATE controllers SET name = 'P345 Pad' WHERE id = ?", (CTRL_IDS[0],))
    conn.commit()
    conn.close()
    client, _csrf = admin_test_client()
    html = client.get(f'/museum/{SYSTEM_ID}').get_data(as_text=True)
    assert 'museum-model-button' not in html
    assert 'museumModelDialog' not in html
    assert 'js/hardware-model.js' not in html
