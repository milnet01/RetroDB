"""PASS-59-106 INV-12 — the version routes refuse a viewer.

docs/specs/PASS-59-106-regional-versions.md §4.5 and §5.
"""
import pytest

from services import version_groups as vg
from tests._versions_util import vdb  # noqa: F401 — fixture

VIEWER = {'id': 1, 'username': 'viewer-stub', 'role': 'viewer'}


def test_control_editor_can_link(vdb, admin_test_client):
    a, b = vdb.game('Alpha'), vdb.game('Alpha', rom='Alpha (Japan).zip')
    client, csrf = admin_test_client()
    resp = client.post('/api/versions/link', json={'game_ids': [a, b]},
                       headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 200, resp.get_data(as_text=True)[:300]
    assert vdb.group_of(a) == resp.get_json()['version_group_id'] == vdb.group_of(b)


@pytest.mark.parametrize('route', ['link', 'unlink', 'reject'])
def test_inv12_viewer_refused(vdb, admin_test_client, route):
    a, b = vdb.game('Alpha'), vdb.game('Alpha', rom='Alpha (Japan).zip')
    c, d = vdb.game('Beta'), vdb.game('Beta', rom='Beta (Japan).zip')
    gid = vg.link([c, d])
    client, csrf = admin_test_client(user=VIEWER)
    url, body = {
        'link': ('/api/versions/link', {'game_ids': [a, b]}),
        'unlink': (f'/api/versions/unlink/{c}', {}),
        'reject': ('/api/versions/reject', {'game_ids': [a, b]}),
    }[route]
    resp = client.post(url, json=body, headers={'X-CSRF-Token': csrf})
    assert resp.status_code == 403
    assert vdb.group_of(a) is None and vdb.group_of(c) == gid
    assert vdb.conn.execute("SELECT COUNT(*) FROM version_link_rejections").fetchone()[0] == 0
