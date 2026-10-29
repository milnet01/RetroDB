"""Regression pins for route-layer fixes from the routes/ review pass.

- Screenshot dedup reads screenshots from IMAGE_PATH (scraped media), not
  the bundle's STATIC_PATH (they differ in a frozen build).
- Multi-disc scan lists each disc file once, matching extensions in any case.
- Auto-assign default controllers prefers the longest folder pattern, so an
  SNES folder is not given the NES controller.
- /api/controllers fetches every controller's systems in one query.
- /api/calculate-storage writes sizes in one batch.
- /api/games/find floors `limit` (a negative LIMIT is unlimited in SQLite).
"""
import os
import threading
from types import SimpleNamespace

from tests.test_pass59_rom_tools import _InlineThread, rom_client  # noqa: F401


# --- Screenshot dedup: IMAGE_PATH -----------------------------------------

def test_screenshot_dedup_scans_image_path(rom_client, monkeypatch, tmp_path):  # noqa: F811
    import routes.tools as tools
    post, _roms = rom_client
    images = tmp_path / 'images'
    (images / 'screenshots').mkdir(parents=True)
    bundle = tmp_path / 'bundle'
    (bundle / 'images' / 'screenshots').mkdir(parents=True)
    for name in ('1_a.png', '1_b.png'):
        (images / 'screenshots' / name).write_bytes(b'same bytes')
    monkeypatch.setattr(tools.config, 'IMAGE_PATH', str(images))
    monkeypatch.setattr(tools.config, 'STATIC_PATH', str(bundle))
    monkeypatch.setattr(tools, 'query', lambda *_a, **_k: [
        {'id': 1, 'title': 'Game', 'screenshots': '1_a.png, 1_b.png', 'system_name': 'NES'}])
    shim = SimpleNamespace(**{**vars(threading), 'Thread': _InlineThread})
    monkeypatch.setattr(tools, 'threading', shim)

    resp = post('/api/rom-tools/screenshot-dedup/scan', {'method': 'hash'})
    task = tools._rom_tool_tasks[resp.get_json()['task_id']]
    assert task['status'] == 'completed'
    assert task['results']['games_with_dupes'] == 1
    assert task['results']['total_duplicates'] == 1


# --- Multi-disc scan: one entry per file, any extension case --------------

def test_disc_files_listed_once_in_any_case(tmp_path):
    from routes.reports import _disc_files_in
    for name in ('Game (Disc 1).bin', 'Game (Disc 2).BIN', 'Other.Iso',
                 'readme.txt', '.hidden.bin'):
        (tmp_path / name).write_bytes(b'x')
    (tmp_path / 'folder.iso').mkdir()
    found = sorted(os.path.basename(p) for p in _disc_files_in(str(tmp_path), ['.bin', '.iso']))
    assert found == ['Game (Disc 1).bin', 'Game (Disc 2).BIN', 'Other.Iso']


def test_single_disc_is_not_reported_as_multi_disc(rom_client, monkeypatch):  # noqa: F811
    import routes.reports as reports
    post, roms = rom_client
    psx = roms / 'psx'
    psx.mkdir()
    (psx / 'Solo (Disc 1).bin').write_bytes(b'x')
    monkeypatch.setattr(reports, 'query', lambda *_a, **_k: {'folder': 'psx'})
    resp = post('/api/reports/multidisc-scan', {'system': 'psx'})
    assert resp.status_code == 200
    assert resp.get_json()['games'] == []


# --- Auto-assign default controllers: longest pattern wins ----------------

def test_assign_default_controller_snes_gets_snes_controller(rom_client, monkeypatch):  # noqa: F811
    import routes.controllers as controllers
    post, _roms = rom_client
    library = [(1, 'NES Controller'), (2, 'SNES Controller'),
               (3, 'Game Boy'), (4, 'Game Boy Advance')]

    def fake_query(sql, args=(), one=False):
        if 'FROM systems' in sql:
            return [{'id': 10, 'name': 'SNES', 'folder': 'snes'},
                    {'id': 11, 'name': 'GBA', 'folder': 'gba'}]
        needle = args[0].strip('%')
        hits = [{'id': cid} for cid, name in library if needle in name]
        return hits[0] if hits else None

    writes = []
    monkeypatch.setattr(controllers, 'query', fake_query)
    monkeypatch.setattr(controllers, 'execute', lambda sql, args=(): writes.append(args))
    resp = post('/api/systems/assign-default-controllers', {})
    assert resp.status_code == 200
    assert dict((sid, cid) for cid, sid in writes) == {10: 2, 11: 4}


# --- /api/controllers: systems in one query -------------------------------

def test_controllers_list_groups_systems_without_n_plus_one(rom_client, monkeypatch):  # noqa: F811
    import app as app_module
    import routes.controllers as controllers
    calls = []

    def fake_query(sql, args=(), one=False):
        calls.append(sql)
        if 'FROM controllers c' in sql:
            return [{'id': 1, 'name': 'Pad'}, {'id': 2, 'name': 'Stick'}]
        return [{'controller_id': 1, 'id': 5, 'name': 'NES'},
                {'controller_id': 1, 'id': 6, 'name': 'SNES'}]
    monkeypatch.setattr(controllers, 'query', fake_query)
    resp = app_module.app.test_client().get('/api/controllers')
    body = resp.get_json()
    assert len(calls) == 2
    by_id = {c['id']: c for c in body['controllers']}
    assert by_id[1]['system_ids'] == [5, 6]
    assert by_id[1]['system_name'] == 'NES, SNES'
    assert by_id[2]['system_ids'] == [] and by_id[2]['system_name'] is None


# --- /api/calculate-storage: one batched write ----------------------------

def test_calculate_storage_batches_writes(rom_client, monkeypatch):  # noqa: F811
    import routes.systems as systems
    post, roms = rom_client
    a, b = roms / 'a.nes', roms / 'b.nes'
    a.write_bytes(b'xx')
    b.write_bytes(b'xxxx')
    monkeypatch.setattr(systems, 'query', lambda *_a, **_k: [
        {'id': 1, 'rom_path': str(a)}, {'id': 2, 'rom_path': str(b)},
        {'id': 3, 'rom_path': str(roms / 'gone.nes')}])
    batches = []
    monkeypatch.setattr(systems, 'execute_many', lambda sql, rows: batches.append(rows))
    resp = post('/api/calculate-storage', {})
    assert resp.get_json()['updated'] == 2
    assert batches == [[(2, 1), (4, 2)]]


# --- /api/games/find: limit floored ---------------------------------------

def test_local_search_floors_negative_limit(rom_client, monkeypatch):  # noqa: F811
    import app as app_module
    import routes.games_search as gs
    seen = []
    monkeypatch.setattr(gs, 'query', lambda sql, args=(): seen.append(args) or [])
    app_module.app.test_client().get('/api/games/find?q=zelda&limit=-1')
    assert seen and seen[0][-1] == 1
