"""PASS-59-326 — a game's 3D box built from its scraped scans.
docs/specs/PASS-59-326-auto-3d-box.md, INV-1 to INV-10.
"""
import io
import json
import os

import numpy as np
import pytest
from PIL import Image

from services import box_faces
from services.box3d import build
from services.database import execute, query


def _picture(path, w, h, colour=(40, 90, 200)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new('RGB', (w, h), colour).save(path, 'WEBP')
    return path.name


@pytest.fixture
def images(tmp_path, monkeypatch):
    root = tmp_path / 'images'
    root.mkdir()
    monkeypatch.setattr('config.IMAGE_PATH', str(root))
    return root


def _system(folder):
    row = query("SELECT id FROM systems WHERE folder = ?", (folder,), one=True)
    return row['id'] if row else execute(
        "INSERT INTO systems (name, folder) VALUES (?, ?)", (f'Probe {folder}', folder))


@pytest.fixture
def make_game(images, setup_complete):
    made = []

    def make(folder='ps2', region='USA', front=(1350, 1900), back=None, scans=None):
        gid = execute("INSERT INTO games (system_id, title, rom_path, region) "
                      "VALUES (?, 'Box Probe', ?, ?)",
                      (_system(folder), f'/x/probe{len(made)}.iso', region))
        made.append(gid)
        if front:
            name = _picture(images / 'boxart' / f'{gid}_boxart.webp', *front)
            execute("UPDATE games SET boxart = ? WHERE id = ?", (name, gid))
        if back:
            name = _picture(images / 'boxart_back' / f'{gid}_back.webp', *back)
            execute("UPDATE games SET boxart_back = ? WHERE id = ?", (name, gid))
        if scans:
            execute("UPDATE games SET box_scans = ? WHERE id = ?", (json.dumps(scans), gid))
        return gid

    yield make
    for gid in made:
        execute("DELETE FROM games WHERE id = ?", (gid,))


def _record(gid):
    value = query("SELECT box_faces FROM games WHERE id = ?", (gid,), one=True)['box_faces']
    return json.loads(value) if value else None


def _files(images):
    folder = images / 'box_faces'
    return sorted(os.listdir(folder)) if folder.exists() else []


def _import(gid, replace=False):
    def png(w, h):
        buf = io.BytesIO()
        Image.new('RGB', (w, h), (200, 30, 30)).save(buf, 'PNG')
        return buf.getvalue()
    box = {'format': 'slipcase-box', 'version': 1,
           'case': {'name': 'PS2 DVD Case', 'width_mm': 135, 'height_mm': 190, 'depth_mm': 14},
           'colours': {'top': '#1C1C1C', 'bottom': '#1C1C1C', 'edge': '#1C1C1C'},
           'faces': {'front': 'S.front.png', 'spine': 'S.spine.png'}}
    return box_faces.import_box_file(gid, {
        'S.box.json': json.dumps(box).encode(),
        'S.front.png': png(270, 380), 'S.spine.png': png(28, 380)}, replace=replace)


def test_a_game_with_a_cover_gets_a_built_box(make_game, images):
    gid = make_game()
    assert build.build_for_game(gid) == 'built'
    record = _record(gid)
    assert record['source'] == 'auto'
    assert record['case']['name'] == 'PS2 DVD Case'
    assert box_faces.faces_for({'box_faces': json.dumps(record)}) is not None


def test_inv1_a_build_never_writes_over_an_imported_box(make_game, images):
    gid = make_game()
    _import(gid)
    before, files = _record(gid), _files(images)
    assert build.build_for_game(gid) == 'imported'
    assert _record(gid) == before and _files(images) == files


def test_inv2_an_import_replaces_a_built_box_without_asking(make_game, images):
    gid = make_game()
    build.build_for_game(gid)
    built_files = _files(images)
    _import(gid, replace=False)
    record = _record(gid)
    assert 'source' not in record
    assert not set(built_files) & set(_files(images))


def test_inv3_unchanged_inputs_write_nothing_and_a_new_back_rebuilds(make_game, images):
    gid = make_game()
    assert build.build_for_game(gid) == 'built'
    first = _files(images)
    assert build.build_for_game(gid) == 'unchanged'
    assert _files(images) == first
    name = _picture(images / 'boxart_back' / f'{gid}_back.webp', 1350, 1900, (10, 200, 10))
    execute("UPDATE games SET boxart_back = ? WHERE id = ?", (name, gid))
    assert build.build_for_game(gid) == 'built'
    assert not set(first) & set(_files(images))
    assert _record(gid)['faces']['back']


def test_inv4_clear_removes_a_built_box_and_keeps_an_imported_one(make_game, images):
    from services.game_cleanup import clear_scraped_data
    built, imported = make_game(), make_game()
    build.build_for_game(built)
    _import(imported)
    kept = _record(imported)
    execute("UPDATE games SET scraped = 1 WHERE id IN (?, ?)", (built, imported))
    clear_scraped_data()
    assert _record(built) is None
    assert _record(imported) == kept
    assert all(name.startswith(f'{imported}_') for name in _files(images))


@pytest.mark.parametrize('folder, region, packaging, expected', [
    ('ps2', 'USA', None, 'PS2 DVD Case'),
    ('psx', 'Europe', None, 'PS1 Jewel Case (PAL)'),
    ('sfc', 'USA', None, 'Super Famicom Cartridge Box'),
    ('pc', 'USA', None, None),
    ('pc', 'USA', 'Jewel Case', 'CD Jewel Case'),
    ('pc', 'USA', 'Box', None),
    ('arcade', 'USA', None, None),
])
def test_inv5_the_case_follows_folder_region_and_packaging(folder, region, packaging, expected):
    case = build.case_for_game(folder, build.region_for(folder, [], region), packaging)
    assert (case.name if case else None) == expected


def test_inv5_the_scanned_box_country_beats_the_game_region(make_game, images):
    assert build.region_for('psx', ['de'], 'USA') == 'PAL'
    assert build.region_for('psx', [], 'Japan') == 'NTSC-J'


def test_inv6_faces_are_webp_and_the_front_at_most_1080_tall(make_game, images):
    big, small = make_game(front=(1700, 2400)), make_game(front=(427, 600))
    build.build_for_game(big)
    build.build_for_game(small)
    for gid, height in ((big, 1080), (small, 600)):
        path = images / 'box_faces' / _record(gid)['faces']['front']
        with Image.open(path) as im:
            assert im.format == 'WEBP' and im.height == height


def _spine_colour(images, gid):
    with Image.open(images / 'box_faces' / _record(gid)['faces']['spine']) as im:
        im = im.convert('RGB')
        return im.getpixel((im.width // 2, im.height // 2))


def test_inv7_a_scanned_spine_is_used_and_none_is_generated(make_game, images):
    scanned = make_game()
    name = _picture(images / 'box_scans' / f'{scanned}_spine_0_ab.webp', 140, 1900, (220, 0, 0))
    execute("UPDATE games SET box_scans = ? WHERE id = ?", (json.dumps({'version': 1, 'mobygames': {
        'items': [{'kind': 'spine', 'caption': 'Left', 'file': name}]}}), scanned))
    generated = make_game()
    build.build_for_game(scanned)
    build.build_for_game(generated)
    r, g, b = _spine_colour(images, scanned)
    assert r > 180 and g < 60 and b < 60
    r, g, b = _spine_colour(images, generated)
    assert r < 100   # PS2's generated spine is black


def test_inv8_a_failed_write_changes_nothing(make_game, images, monkeypatch):
    gid = make_game()

    def broken(path, data):
        raise OSError('disk full')
    monkeypatch.setattr('services.atomic_io.atomic_write_bytes', broken)
    assert build.build_for_game(gid) == 'failed'
    assert _record(gid) is None and _files(images) == []


def test_inv9_the_running_mean_matches_scipy():
    from services.box3d.image_ops import uniform_filter1d
    values = np.array([3., 1., 4., 1., 5., 9., 2.])
    # scipy.ndimage.uniform_filter1d(values, size=n) under SciPy 1.17.1.
    expected = {
        2: [3.0, 2.0, 2.5, 2.5, 3.0, 7.0, 5.5],
        3: [2.333333, 2.666667, 2.0, 3.333333, 5.0, 5.333333, 4.333333],
        4: [2.0, 2.75, 2.25, 2.75, 4.75, 4.25, 4.5],
        9: [2.555556, 3.444444, 3.222222, 3.333333, 4.0, 4.222222, 4.222222],
    }
    for size, want in expected.items():
        assert np.allclose(uniform_filter1d(values, size), want, atol=1e-5), size


def test_no_front_and_no_case_build_nothing(make_game, images):
    assert build.build_for_game(make_game(front=None)) == 'no_front'
    assert build.build_for_game(make_game(folder='arcade')) == 'no_case'
    assert _files(images) == []


def test_inv10_only_an_admin_starts_or_cancels_the_job(admin_test_client, monkeypatch):
    from services.jobs import box_build_job
    started = []
    monkeypatch.setattr(box_build_job, 'start', lambda: started.append(1) or {'success': True})
    for role in ('viewer', 'editor'):
        client, csrf = admin_test_client(user={'id': 2, 'username': f'{role}-stub', 'role': role})
        for action in ('start', 'cancel'):
            reply = client.post(f'/api/maintenance/box-build/{action}', headers={'X-CSRF-Token': csrf})
            assert reply.status_code == 403, (role, action)
    client, csrf = admin_test_client()
    assert client.post('/api/maintenance/box-build/start',
                       headers={'X-CSRF-Token': csrf}).status_code == 200
    assert started == [1]


def test_inv10_a_signed_in_user_reads_the_status(admin_test_client):
    client, _ = admin_test_client(user={'id': 2, 'username': 'viewer-stub', 'role': 'viewer'})
    assert client.get('/api/maintenance/box-build/status').get_json()['success'] is True


def test_inv10_a_signed_out_visitor_is_refused_the_status(anon_client, assert_sign_in_refused):
    path = '/api/maintenance/box-build/status'
    assert_sign_in_refused(anon_client.get(path), path)


def test_the_job_builds_only_games_without_an_imported_box(make_game, images):
    from services.jobs.box_build import BoxBuildJob
    to_build, imported, arcade = make_game(), make_game(), make_game(folder='arcade')
    _import(imported)
    kept = _record(imported)
    job = BoxBuildJob()
    assert job.start()['success']
    job._thread.join(timeout=60)
    status = job.get_status()
    assert status['completed'] and status['success_count'] >= 1
    assert _record(to_build)['source'] == 'auto'
    assert _record(imported) == kept
    assert _record(arcade) is None
