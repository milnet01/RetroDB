"""PASS-59-106 INV-11 — the Duplicate Finder does not call two versions of one
game duplicates in name mode, and still reports identical bytes in hash mode.

docs/specs/PASS-59-106-regional-versions.md §4.6 and §5.
"""
import time

import pytest

import routes.tools as tools
from services import version_groups as vg
from tests._versions_util import vdb  # noqa: F401 — fixture


@pytest.fixture
def scan(admin_test_client, monkeypatch, tmp_path):
    # The scan route allows 5 calls a minute; leave the budget as found.
    import app as app_module
    app_module.limiter.reset()
    monkeypatch.setattr(tools, '_get_rom_path', lambda: str(tmp_path))
    client, csrf = admin_test_client()

    def run(method):
        resp = client.post('/api/rom-tools/duplicate-finder/scan',
                           json={'path': str(tmp_path), 'method': method,
                                 'ignore_region': True},
                           headers={'X-CSRF-Token': csrf})
        assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
        task_id = resp.get_json()['task_id']
        for _ in range(200):
            task = client.get(f'/api/rom-tools/task/{task_id}').get_json()
            if task['status'] != 'running':
                break
            time.sleep(0.05)
        assert task['status'] == 'completed', task
        return task['results']['groups']
    yield run
    app_module.limiter.reset()


def _files(vdb, tmp_path, same_bytes):
    paths = []
    for region in ('USA', 'Japan'):
        p = tmp_path / f'Game ({region}).zip'
        p.write_bytes(b'same' if same_bytes else region.encode())
        paths.append(vdb.game('Game', rom=p.name, rom_path=str(p)))
    return paths


def test_inv11_unlinked_files_are_name_duplicates(vdb, scan, tmp_path):
    _files(vdb, tmp_path, same_bytes=False)
    assert len(scan('name')) == 1


def test_inv11_linked_files_are_not_name_duplicates(vdb, scan, tmp_path):
    vg.link(_files(vdb, tmp_path, same_bytes=False))
    assert scan('name') == []


def test_inv11_linked_identical_files_are_hash_duplicates(vdb, scan, tmp_path):
    vg.link(_files(vdb, tmp_path, same_bytes=True))
    assert len(scan('hash')) == 1
