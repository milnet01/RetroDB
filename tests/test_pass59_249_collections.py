"""PASS-59-249 group J: collections, achievements, trophies and ROM tools.

Each test pins one finding from the 2026-11-04 audit
(docs/reviews/close-findings-2026-11-05-pass-59-249.md, group J).
"""
import pytest

from tests._versions_util import vdb  # noqa: F401  (a fixture)

EDITOR = {'id': 5, 'username': 'editor-stub', 'role': 'editor'}
OTHER_EDITOR = {'id': 6, 'username': 'editor-two', 'role': 'editor'}


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    import app as app_module
    app_module.limiter.reset()
    yield
    app_module.limiter.reset()


# --- RA links ----------------------------------------------------------------------

def test_clearing_ra_data_clears_whether_the_copy_fits(vdb, admin_test_client):  # noqa: F811
    game_id = vdb.game('RA Probe', ra_game_id=9, ra_title='X', has_retroachievements=1, ra_copy_fits=1)
    client, csrf = admin_test_client()
    client.post(f'/api/clear-ra-data/{vdb.sid}', headers={'X-CSRF-Token': csrf})
    row = vdb.conn.execute("SELECT ra_game_id, ra_copy_fits FROM games WHERE id = ?", (game_id,)).fetchone()
    assert tuple(row) == (None, None)


@pytest.mark.parametrize('path', [r'C:\Roms\snes\Super Mario World (USA).sfc',
                                  '/roms/snes/Super Mario World (USA).sfc'])
def test_ra_rom_name_reads_either_kind_of_path(path):
    from services.achievement_linking import ra_rom_name
    assert ra_rom_name(path) == 'Super Mario World (USA)'


# --- Tags, lists and the wishlist --------------------------------------------------

def _send(client, csrf, method, url, body):
    return getattr(client, method)(url, json=body, headers={'X-CSRF-Token': csrf})


@pytest.mark.parametrize('body', [{'name': None}, {'name': 5}, {'name': 'Ok', 'color': 'red; x'},
                                  {'name': 'Ok', 'color': None}])
def test_a_bad_tag_is_refused_not_a_500(admin_test_client, body):
    client, csrf = admin_test_client()
    assert _send(client, csrf, 'post', '/api/tags', body).status_code == 400


@pytest.mark.parametrize('body', [{'name': None}, {'name': ''}, {'color': '#12'}])
def test_a_bad_tag_edit_is_refused_not_a_500(vdb, admin_test_client, body):  # noqa: F811
    client, csrf = admin_test_client()
    tag = _send(client, csrf, 'post', '/api/tags', {'name': 'P59249 tag', 'color': '#112233'}).get_json()['tag']
    try:
        assert _send(client, csrf, 'put', f"/api/tags/{tag['id']}", body).status_code == 400
    finally:
        vdb.conn.execute("DELETE FROM tags WHERE id = ?", (tag['id'],))
        vdb.conn.commit()


@pytest.mark.parametrize('body', [{'name': None}, {'name': ''}, {'sort_order': 'first'},
                                  {'description': 5}])
def test_a_bad_list_edit_is_refused(vdb, admin_test_client, body):  # noqa: F811
    client, csrf = admin_test_client()
    lst = _send(client, csrf, 'post', '/api/lists', {'name': 'P59249 list'}).get_json()['list']
    try:
        assert _send(client, csrf, 'put', f"/api/lists/{lst['id']}", body).status_code == 400
    finally:
        vdb.conn.execute("DELETE FROM lists WHERE id = ?", (lst['id'],))
        vdb.conn.commit()


def test_a_list_with_no_name_is_refused_not_a_500(admin_test_client):
    client, csrf = admin_test_client()
    assert _send(client, csrf, 'post', '/api/lists', {'name': None}).status_code == 400


def test_renaming_a_wish_onto_another_is_refused(vdb, admin_test_client):  # noqa: F811
    client, csrf = admin_test_client()
    ids = [_send(client, csrf, 'post', '/api/wishlist', {'title': t}).get_json()['item']['id']
           for t in ('P59249 Wish A', 'P59249 Wish B')]
    try:
        reply = _send(client, csrf, 'put', f'/api/wishlist/{ids[1]}', {'title': 'p59249 wish a'})
        assert reply.status_code == 409
    finally:
        vdb.conn.execute("DELETE FROM wishlist WHERE title LIKE 'P59249 Wish%'")
        vdb.conn.commit()


# --- ROM tools: who may pause or cancel --------------------------------------------

@pytest.fixture
def task():
    from routes import tools
    task_id = 'p59249-task'
    tools._rom_tool_tasks[task_id] = {'status': 'running', 'started_by': EDITOR['id']}
    yield task_id
    tools._rom_tool_tasks.pop(task_id, None)


@pytest.mark.parametrize('user, allowed', [
    (EDITOR, True), (OTHER_EDITOR, False),
    ({'id': EDITOR['id'], 'username': 'viewer', 'role': 'viewer'}, False)])
def test_an_editor_controls_the_scan_they_started(task, admin_test_client, user, allowed):
    client, csrf = admin_test_client(user=user)
    reply = client.post(f'/api/rom-tools/task/{task}/pause', headers={'X-CSRF-Token': csrf})
    assert (reply.status_code == 200) is allowed
    if allowed:
        assert client.post(f'/api/rom-tools/task/{task}/resume', headers={'X-CSRF-Token': csrf}).status_code == 200
        assert client.post(f'/api/rom-tools/task/{task}/cancel', headers={'X-CSRF-Token': csrf}).status_code == 200


def test_an_admin_controls_any_scan(task, admin_test_client):
    client, csrf = admin_test_client()
    assert client.post(f'/api/rom-tools/task/{task}/cancel', headers={'X-CSRF-Token': csrf}).status_code == 200


def test_an_editor_controls_a_scan_task_they_started():
    from scraper.rom_tools import create_task
    assert create_task('archive_scan', started_by=EDITOR['id']).started_by == EDITOR['id']


# --- Collector rank ------------------------------------------------------------------

def test_a_removed_trophy_counts_toward_no_rank():
    from routes.collector_trophies import compute_collector_rank
    rank = compute_collector_rank([{'id': 'p59249_removed', 'tier': 'platinum', 'earned_at': 'x'}])
    assert rank['points'] == 0 and rank['earned_count'] == 0
