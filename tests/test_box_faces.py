"""PASS-59-142 — importing a Slipcase box file onto a game.
docs/specs/PASS-59-142-box-file-import.md, INV-1 to INV-7.
"""
import io
import json
import os

import pytest
from PIL import Image

from services import box_faces
from services.box_faces import BoxImportError
from services.database import execute, query


def _png(w, h, colour=(200, 30, 30), mode='RGB'):
    buf = io.BytesIO()
    Image.new(mode, (w, h), colour).save(buf, 'PNG')
    return buf.getvalue()


def _box(**changes):
    data = {
        'format': 'slipcase-box', 'version': 1, 'generator': 'Slipcase 1.4.0',
        'case': {'name': 'PS2 DVD Case', 'width_mm': 135, 'height_mm': 190, 'depth_mm': 14},
        'colours': {'top': '#1c1c1c', 'bottom': '#1C1C1C', 'edge': '#102030'},
        'faces': {'front': 'S.front.png', 'spine': 'S.spine.png', 'back': 'S.back.png'},
    }
    data.update(changes)
    return json.dumps(data).encode()


def _uploads(box=None, **extra):
    files = {
        'S.box.json': box if box is not None else _box(),
        'S.front.png': _png(270, 380),
        'S.spine.png': _png(28, 380),
        'S.back.png': _png(270, 380),
    }
    files.update(extra)
    return files


@pytest.fixture
def images(tmp_path, monkeypatch):
    root = tmp_path / 'images'
    (root / 'boxart_3d').mkdir(parents=True)
    monkeypatch.setattr('config.IMAGE_PATH', str(root))
    return root


@pytest.fixture
def game(images, setup_complete):
    sid = execute("INSERT INTO systems (name, folder) VALUES ('BoxProbe', 'boxprobe')")
    gid = execute("INSERT INTO games (system_id, title, rom_path, boxart_3d) "
                  "VALUES (?, 'Box Game', '/x/box.iso', ?)", (sid, f'{0}_3d.webp'))
    yield gid
    execute("DELETE FROM games WHERE id = ?", (gid,))
    execute("DELETE FROM systems WHERE id = ?", (sid,))


def _row(gid):
    return query("SELECT box_faces, boxart_3d FROM games WHERE id = ?", (gid,), one=True)


def _stored_files(images):
    folder = images / 'box_faces'
    return sorted(os.listdir(folder)) if folder.exists() else []


def test_migration_adds_the_column(game):
    assert _row(game)['box_faces'] is None


def test_import_stores_each_face_and_the_record(game, images):
    record = box_faces.import_box_file(game, _uploads())
    assert record['case'] == {'name': 'PS2 DVD Case', 'width_mm': 135,
                              'height_mm': 190, 'depth_mm': 14}
    assert record['colours'] == {'top': '#1C1C1C', 'bottom': '#1C1C1C', 'edge': '#102030'}
    faces = record['faces']
    assert set(faces) == set(box_faces.FACES)
    assert faces['edge'] is None and faces['top'] is None and faces['bottom'] is None
    assert _stored_files(images) == sorted(faces[f] for f in ('front', 'spine', 'back'))
    assert record['urls']['front'] == f"images/box_faces/{faces['front']}"
    assert json.loads(_row(game)['box_faces'])['faces'] == faces


# --- INV-1: a refused box file writes nothing --------------------------------

def _drop(name):
    files = _uploads()
    del files[name]
    return files


@pytest.mark.parametrize('uploads, code', [
    (_drop('S.box.json'), 'no_box_file'),
    (_uploads(**{'T.box.json': _box()}), 'two_box_files'),
    (_uploads(box=b'{not json'), 'bad_json'),
    (_uploads(box=b'[1, 2]'), 'bad_json'),
    (_uploads(box=b' ' * (64 * 1024 + 1)), 'bad_json'),
    (_uploads(box=_box(format='other-box')), 'bad_box_file'),
    (_uploads(box=_box(version=2)), 'bad_box_file'),
    (_uploads(box=_box(version='1')), 'bad_box_file'),
    (_uploads(box=_box(case={'name': '', 'width_mm': 135, 'height_mm': 190, 'depth_mm': 14})),
     'bad_box_file'),
    (_uploads(box=_box(case={'name': 'X', 'width_mm': 0, 'height_mm': 190, 'depth_mm': 14})),
     'bad_box_file'),
    (_uploads(box=_box(case={'name': 'X', 'width_mm': 135, 'height_mm': 1001, 'depth_mm': 14})),
     'bad_box_file'),
    (_uploads(box=_box(colours={'top': '#1C1C1C', 'bottom': 'black', 'edge': '#1C1C1C'})),
     'bad_box_file'),
    (_uploads(box=_box(faces={'front': 'S.front.png', 'spine': None})), 'bad_box_file'),
    (_uploads(box=_box(faces={'front': 'S.front.png', 'spine': '../S.spine.png'})),
     'bad_face_name'),
    (_uploads(box=_box(faces={'front': 'S.front.png', 'spine': '.S.spine.png'})),
     'bad_face_name'),
    (_uploads(box=_box(faces={'front': 'S.front.png', 'spine': 'S.spine.png',
                              'edge': 'S.edge.png'})), 'missing_face'),
    (_uploads(**{'S.back.png': b'MZ\x90\x00 not a picture'}), 'bad_image'),
    (_uploads(**{'S.back.png': b'\x89PNG' + b'\x00' * (10 * 1024 * 1024)}), 'face_too_large'),
], ids=lambda v: v if isinstance(v, str) else '')
def test_inv1_a_refused_box_file_writes_nothing(game, images, uploads, code):
    with pytest.raises(BoxImportError) as caught:
        box_faces.import_box_file(game, uploads)
    assert caught.value.code == code
    assert _stored_files(images) == []
    assert _row(game)['box_faces'] is None


def test_inv1_an_unknown_game_writes_nothing(images, setup_complete):
    with pytest.raises(BoxImportError) as caught:
        box_faces.import_box_file(999_999_999, _uploads())
    assert caught.value.code == 'not_found'
    assert _stored_files(images) == []


def test_a_failed_write_removes_the_faces_already_written(game, images, monkeypatch):
    import services.atomic_io as atomic_io
    real = atomic_io.atomic_write_bytes
    calls = []

    def fail_second(path, data):
        calls.append(path)
        if len(calls) == 2:
            raise OSError('disk full')
        real(path, data)

    monkeypatch.setattr(atomic_io, 'atomic_write_bytes', fail_second)
    with pytest.raises(BoxImportError) as caught:
        box_faces.import_box_file(game, _uploads())
    assert caught.value.code == 'write_failed'
    assert _stored_files(images) == []
    assert _row(game)['box_faces'] is None


# --- INV-2: WebP, one scale factor, never enlarged ---------------------------

def _sizes(images, record):
    out = {}
    for face, name in record['faces'].items():
        if name:
            with Image.open(images / 'box_faces' / name) as im:
                out[face] = (im.format, im.size)
    return out


def test_inv2_every_face_shares_the_fronts_scale(game, images):
    box = _box(faces={'front': 'S.front.png', 'spine': 'S.spine.png', 'top': 'S.top.png'})
    uploads = {'S.box.json': box, 'S.front.png': _png(1137, 1600),
               'S.spine.png': _png(118, 1600), 'S.top.png': _png(1137, 118)}
    sizes = _sizes(images, box_faces.import_box_file(game, uploads))
    assert sizes['front'] == ('WEBP', (round(1137 * 1080 / 1600), 1080))
    assert sizes['spine'] == ('WEBP', (round(118 * 1080 / 1600), 1080))
    assert sizes['top'] == ('WEBP', (round(1137 * 1080 / 1600), round(118 * 1080 / 1600)))


def test_inv2_a_small_front_is_not_enlarged(game, images):
    uploads = _uploads(**{'S.front.png': _png(640, 900), 'S.spine.png': _png(66, 900),
                          'S.back.png': _png(640, 900)})
    sizes = _sizes(images, box_faces.import_box_file(game, uploads))
    assert sizes['front'] == ('WEBP', (640, 900))
    assert sizes['spine'] == ('WEBP', (66, 900))


def test_transparency_is_flattened_onto_the_edge_colour(game, images):
    uploads = _uploads(**{'S.back.png': _png(270, 380, (0, 0, 0, 0), mode='RGBA')})
    record = box_faces.import_box_file(game, uploads)
    with Image.open(images / 'box_faces' / record['faces']['back']) as im:
        assert im.mode == 'RGB'
        r, g, b = im.getpixel((10, 10))
    assert abs(r - 0x10) <= 3 and abs(g - 0x20) <= 3 and abs(b - 0x30) <= 3


# --- INV-3 and INV-4: fill-only, and a clean replace -------------------------

def test_inv3_a_second_import_without_replace_changes_nothing(game, images):
    first = box_faces.import_box_file(game, _uploads())
    before_files, before_row = _stored_files(images), _row(game)['box_faces']
    with pytest.raises(BoxImportError) as caught:
        box_faces.import_box_file(game, _uploads())
    assert caught.value.code == 'exists'
    assert _stored_files(images) == before_files
    assert _row(game)['box_faces'] == before_row
    assert first['faces']['front'] in before_files


def test_inv4_a_replace_leaves_only_the_new_files(game, images):
    old = box_faces.import_box_file(game, _uploads())
    new = box_faces.import_box_file(game, _uploads(), replace=True)
    assert new['faces']['front'] != old['faces']['front']
    assert _stored_files(images) == sorted(new['faces'][f] for f in ('front', 'spine', 'back'))
    assert json.loads(_row(game)['box_faces'])['faces'] == new['faces']


def test_missing_front_file_counts_as_no_faces(game, images):
    record = box_faces.import_box_file(game, _uploads())
    os.remove(images / 'box_faces' / record['faces']['front'])
    assert box_faces.faces_for(_row(game)) is None
    box_faces.import_box_file(game, _uploads())  # no replace needed


# --- INV-5: deletes stay inside the faces folder -----------------------------

def test_inv5_removal_never_leaves_the_folder_or_follows_a_symlink(game, images, tmp_path):
    outside = images / 'boxart' / 'x.webp'
    outside.parent.mkdir()
    outside.write_bytes(b'keep me')
    target = tmp_path / 'target.webp'
    target.write_bytes(b'keep me too')
    (images / 'box_faces').mkdir()
    os.symlink(target, images / 'box_faces' / 'link.webp')
    record = {'version': 1, 'faces': {'front': '../boxart/x.webp', 'spine': 'link.webp'}}
    execute("UPDATE games SET box_faces = ? WHERE id = ?", (json.dumps(record), game))

    assert box_faces.remove_box_faces(game) is True
    assert outside.read_bytes() == b'keep me'
    assert target.read_bytes() == b'keep me too'
    assert os.path.islink(images / 'box_faces' / 'link.webp')
    assert _row(game)['box_faces'] is None


def test_inv5_a_symlink_to_a_face_inside_the_folder_is_not_followed(game, images):
    folder = images / 'box_faces'
    folder.mkdir()
    (folder / 'real.webp').write_bytes(b'another game')
    os.symlink(folder / 'real.webp', folder / 'link.webp')
    record = {'version': 1, 'faces': {'front': 'link.webp', 'spine': 'link.webp'}}
    execute("UPDATE games SET box_faces = ? WHERE id = ?", (json.dumps(record), game))

    assert box_faces.faces_for(_row(game)) is None
    box_faces.remove_box_faces(game)
    assert (folder / 'real.webp').read_bytes() == b'another game'


def test_remove_deletes_the_files_and_clears_the_row(game, images):
    box_faces.import_box_file(game, _uploads())
    assert box_faces.remove_box_faces(game) is True
    assert _stored_files(images) == []
    assert _row(game)['box_faces'] is None
    assert box_faces.remove_box_faces(game) is False


# --- INV-6: boxart_3d is never touched ---------------------------------------

def test_inv6_boxart_3d_is_untouched(game, images):
    cover = images / 'boxart_3d' / '0_3d.webp'
    cover.write_bytes(b'3d cover')
    box_faces.import_box_file(game, _uploads())
    box_faces.import_box_file(game, _uploads(), replace=True)
    box_faces.remove_box_faces(game)
    assert _row(game)['boxart_3d'] == '0_3d.webp'
    assert cover.read_bytes() == b'3d cover'


# --- Routes, and INV-7: editors only -----------------------------------------

def _post(client, csrf, gid, files, replace=False):
    data = {'files': [(io.BytesIO(raw), name) for name, raw in files.items()]}
    if replace:
        data['replace'] = '1'
    return client.post(f'/api/games/{gid}/box-faces', data=data,
                       content_type='multipart/form-data', headers={'X-CSRF-Token': csrf})


def test_route_imports_then_refuses_a_second_import_with_409(game, images, admin_test_client):
    client, csrf = admin_test_client()
    resp = _post(client, csrf, game, _uploads())
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert resp.get_json()['data']['box_faces']['case']['name'] == 'PS2 DVD Case'

    again = _post(client, csrf, game, _uploads())
    assert again.status_code == 409
    assert again.get_json()['reason'] == 'exists'
    assert _post(client, csrf, game, _uploads(), replace=True).status_code == 200


def test_route_reports_the_reason_for_a_bad_box_file(game, images, admin_test_client):
    client, csrf = admin_test_client()
    resp = _post(client, csrf, game, _drop('S.spine.png'))
    assert resp.status_code == 400
    assert resp.get_json()['reason'] == 'missing_face'


def test_route_delete_removes_the_faces(game, images, admin_test_client):
    client, csrf = admin_test_client()
    _post(client, csrf, game, _uploads())
    resp = client.delete(f'/api/games/{game}/box-faces', headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200
    assert resp.get_json()['data']['removed'] is True
    assert _stored_files(images) == []


def test_inv7_a_viewer_is_refused(game, images, admin_test_client):
    client, csrf = admin_test_client(user={'id': 2, 'username': 'viewer-stub', 'role': 'viewer'})
    assert _post(client, csrf, game, _uploads()).status_code == 403
    assert client.delete(f'/api/games/{game}/box-faces',
                         headers={'X-CSRF-Token': csrf}).status_code == 403
    assert _stored_files(images) == []


# --- §4.5: the import is in the Edit window, the hint under the cover -----------

def _modal_and_cover(client, gid):
    html = client.get(f'/game/{gid}').get_data(as_text=True)
    modal_start = html.index('id="editModal"')
    return html[modal_start:html.index('id="boxartZoomModal"')], html[:modal_start]


def test_the_import_button_is_in_the_edit_window_for_an_editor(game, images, admin_test_client):
    client, _ = admin_test_client()
    modal, cover = _modal_and_cover(client, game)
    assert 'id="boxFacesImportBtn"' in modal
    assert 'id="boxFacesImportBtn"' not in cover


def test_a_viewer_gets_no_import_button(game, images, admin_test_client):
    client, _ = admin_test_client(user={'id': 2, 'username': 'viewer-stub', 'role': 'viewer'})
    modal, _cover = _modal_and_cover(client, game)
    assert 'id="boxFacesImportBtn"' not in modal


def test_the_cover_hint_shows_only_once_the_game_has_faces(game, images, admin_test_client):
    client, _ = admin_test_client(user={'id': 2, 'username': 'viewer-stub', 'role': 'viewer'})
    _modal, cover = _modal_and_cover(client, game)
    assert 'id="boxFacesHint" hidden' in cover
    box_faces.import_box_file(game, _uploads())
    _modal, cover = _modal_and_cover(client, game)
    assert 'id="boxFacesHint">' in cover
