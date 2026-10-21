# =============================================================================
# PASS-59-149 — a game with no ROM file offers no Play and no emulator settings
# =============================================================================
# A game imported from CLZ, Steam, Xbox or PSN has a placeholder rom_path and
# nothing to play. Its page shows no Play button, no Emulator settings panel
# and no Launch section in the edit window. The rule is the library cards'
# (launch_resolver.rom_launch_problem), so the page and the cards agree.
# =============================================================================

import pytest

from tests._versions_util import vdb  # noqa: F401 — fixture

_LAUNCH_BITS = ('id="play-btn"', 'id="emuSettingsPanel"', 'id="edit_emulator_override_id"')


@pytest.fixture
def page(admin_test_client, monkeypatch):
    client, _ = admin_test_client()
    monkeypatch.setattr('routes.games.rom_launch_problem',
                        lambda rom_path: None if rom_path.startswith('/roms/') else 'no file')

    def get(game_id):
        resp = client.get(f'/game/{game_id}')
        assert resp.status_code == 200, resp.status_code
        return resp.get_data(as_text=True)
    return get


@pytest.mark.parametrize('rom_path', ['steam_import/123', 'clz_import/Game'])
def test_imported_game_has_no_launch_controls(vdb, page, rom_path):
    html = page(vdb.game('Imported', rom_path=rom_path))

    for bit in _LAUNCH_BITS:
        assert bit not in html, bit


def test_game_with_a_rom_keeps_its_launch_controls(vdb, page):
    html = page(vdb.game('Real', rom_path='/roms/p59149/Real (USA).zip'))

    for bit in _LAUNCH_BITS:
        assert bit in html, bit


def test_saving_without_the_launch_section_keeps_the_launch_choices(
        vdb, admin_test_client):
    # The Launch section is absent whenever the ROM file is (a moved drive,
    # say); saving the edit window then must not blank what it would show.
    vdb.conn.execute("INSERT OR IGNORE INTO emulators (id, name, binary_name, args_template) "
                     "VALUES (91490, 'p59149', 'p59149', '{rom}')")
    vdb.conn.commit()
    game_id = vdb.game('Kept', emulator_override_id=91490, launch_args_override='--keep-me')
    client, csrf = admin_test_client()

    resp = client.post(f'/game/{game_id}', data={
        'action': 'edit_metadata', 'edit_title': 'Kept'}, headers={'X-CSRF-Token': csrf})

    assert resp.status_code == 200
    row = vdb.conn.execute("SELECT emulator_override_id, launch_args_override FROM games "
                           "WHERE id = ?", (game_id,)).fetchone()
    vdb.conn.execute("DELETE FROM emulators WHERE id = 91490")
    vdb.conn.commit()
    assert tuple(row) == (91490, '--keep-me')
