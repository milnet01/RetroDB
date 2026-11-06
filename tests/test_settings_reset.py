"""Reset to defaults must not reopen the sign-in-free setup pages (PASS-59-265).

`/api/setup` and `/api/setup/browse-folders` answer without a sign-in while
settings say setup is not done and no ROM path is set. A reset that wiped
`setup_completed` and `rom_path` reopened them until an admin redid setup.
"""
import settings_manager


def _capture_save(monkeypatch, current):
    saved = {}
    monkeypatch.setattr(settings_manager, 'load_settings', lambda: dict(current))
    monkeypatch.setattr(settings_manager, 'save_settings',
                        lambda s: saved.update(s) or True)
    return saved


def test_reset_keeps_setup_done_and_rom_path(monkeypatch):
    saved = _capture_save(monkeypatch, {
        'setup_completed': True, 'rom_path': '/roms', 'items_per_page': 7})

    assert settings_manager.reset_to_defaults()

    assert saved['setup_completed'] is True
    assert saved['rom_path'] == '/roms'
    assert saved['items_per_page'] == settings_manager.DEFAULT_SETTINGS['items_per_page']


def test_reset_before_setup_stays_unset(monkeypatch):
    saved = _capture_save(monkeypatch, {})

    assert settings_manager.reset_to_defaults()

    assert saved['setup_completed'] is False
    assert saved['rom_path'] == ''


def test_reset_route_asks_for_no_restart(admin_test_client, monkeypatch):
    client, csrf = admin_test_client()
    monkeypatch.setattr(settings_manager, 'reset_to_defaults', lambda: True)

    resp = client.post('/api/settings/reset', headers={'X-CSRF-Token': csrf})

    body = resp.get_json()
    assert body['success'] is True
    assert body.get('restart_required') in (None, False)
