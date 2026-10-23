"""Next disk for a RetroArch game started from a .m3u (2026-10-20 request).

The disk swap reaches the running RetroArch over its network command port,
so the service is tested against a real UDP socket standing in for it.
"""
import socket
import threading
from unittest.mock import MagicMock

import pytest

from services import retroarch_command
from services.retroarch_command import RetroArchNotListening, next_disk
from tests.test_routes_launch import _make_authed_client

CSRF = {'X-CSRF-Token': 'test-csrf-token'}


@pytest.fixture
def fake_retroarch():
    """A UDP listener that answers GET_STATUS as RetroArch does."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(('127.0.0.1', 0))
    sock.settimeout(3)
    received = []

    def serve():
        for _ in range(2):
            try:
                data, addr = sock.recvfrom(4096)
            except OSError:
                return
            received.append(data)
            if data == b'GET_STATUS':
                sock.sendto(b'GET_STATUS PLAYING vice_x64sc,tmnt,crc32=0', addr)

    t = threading.Thread(target=serve, daemon=True)
    t.start()
    yield sock.getsockname()[1], received, t
    sock.close()


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def test_next_disk_probes_then_sends_disk_next(fake_retroarch):
    port, received, t = fake_retroarch
    next_disk(port=port)
    t.join(3)
    assert received == [b'GET_STATUS', b'DISK_NEXT']


def test_next_disk_with_nothing_listening_raises():
    with pytest.raises(RetroArchNotListening):
        next_disk(port=_free_port(), timeout_s=0.5)


@pytest.fixture
def app_module(monkeypatch):
    import app as mod
    monkeypatch.setitem(mod.app.config, 'TESTING', True)
    return mod


@pytest.fixture
def running(monkeypatch):
    """One running launch, token tok-1, with _game_info stubbed per test."""
    handle = MagicMock(token='tok-1', pid=42, game_id=7, emulator_id=1, started_at=1.0)
    launcher = MagicMock()
    launcher.active.return_value = [handle]
    launcher.command_port.return_value = None   # the user's own RetroArch
    monkeypatch.setattr('routes.launch.get_launcher', lambda: launcher)

    def set_info(**info):
        set_info.launcher = launcher
        monkeypatch.setattr('routes.launch._game_info', lambda h: info)
    return set_info


def test_disk_next_route_sends(app_module, monkeypatch, running):
    running(title='TMNT', disk_swap=True)
    sent = []
    monkeypatch.setattr('routes.launch.next_disk', lambda port: sent.append(port))
    client = _make_authed_client(app_module, monkeypatch, 'player')
    rv = client.post('/api/launch/tok-1/disk-next', headers=CSRF)
    assert rv.status_code == 200
    assert sent == [retroarch_command.RETROARCH_COMMAND_PORT]


def test_disk_next_route_uses_the_players_port(app_module, monkeypatch, running):
    # PASS-59-139: the player listens on the port its launch chose.
    running(title='Crash', disk_swap=True)
    running.launcher.command_port.return_value = 50123
    sent = []
    monkeypatch.setattr('routes.launch.next_disk', lambda port: sent.append(port))
    client = _make_authed_client(app_module, monkeypatch, 'player')
    assert client.post('/api/launch/tok-1/disk-next', headers=CSRF).status_code == 200
    assert sent == [50123]
    running.launcher.command_port.assert_called_once_with('tok-1')


def test_disk_next_route_refuses_a_game_without_disk_list(app_module, monkeypatch, running):
    running(title='Pitfall', disk_swap=False)
    monkeypatch.setattr('routes.launch.next_disk',
                        lambda port: pytest.fail('must not send to RetroArch'))
    client = _make_authed_client(app_module, monkeypatch, 'player')
    assert client.post('/api/launch/tok-1/disk-next', headers=CSRF).status_code == 409


def test_disk_next_route_unknown_token_is_404(app_module, monkeypatch, running):
    running(title='TMNT', disk_swap=True)
    client = _make_authed_client(app_module, monkeypatch, 'player')
    assert client.post('/api/launch/gone/disk-next', headers=CSRF).status_code == 404


def test_disk_next_route_says_how_to_turn_commands_on(app_module, monkeypatch, running):
    running(title='TMNT', disk_swap=True)

    def not_listening(port):
        raise RetroArchNotListening('refused')
    monkeypatch.setattr('routes.launch.next_disk', not_listening)
    client = _make_authed_client(app_module, monkeypatch, 'player')
    rv = client.post('/api/launch/tok-1/disk-next', headers=CSRF)
    assert rv.status_code == 409
    assert str(retroarch_command.RETROARCH_COMMAND_PORT) in rv.get_json()['error']


@pytest.mark.parametrize('rom,is_retroarch,is_player,swap', [
    ('/roms/c64/Game (1990).m3u', 1, 0, True),
    ('/roms/c64/Game (1990).M3U', 1, 0, True),
    ('/roms/c64/Game (1990).zip', 1, 0, False),
    ('/roms/psx/Game (1996).m3u', 0, 0, False),   # a standalone emulator
    ('/roms/psx/Game (1996).m3u', 0, 1, True),    # the player (PASS-59-139)
    ('/roms/psx/Game (1996).cue', 0, 1, False),
])
def test_game_info_flags_retroarch_m3u_only(app_module, rom, is_retroarch, is_player, swap):
    from routes.launch import _game_info
    from services.database import execute
    emu = execute("INSERT INTO emulators (name, binary_name, args_template, is_retroarch, "
                  "is_player) VALUES (?, ?, ?, ?, ?)",
                  ('Disk Test Emu', 'disktest', '{rom}', is_retroarch, is_player))
    sys_id = execute("INSERT INTO systems (name, folder) VALUES (?, ?)",
                     ('Disk Test System', 'disk-test-system'))
    game = execute("INSERT INTO games (system_id, title, rom_path) VALUES (?, ?, ?)",
                   (sys_id, 'Disk Test Game', rom))
    try:
        info = _game_info(MagicMock(game_id=game, emulator_id=emu))
        assert info == {'title': 'Disk Test Game', 'disk_swap': swap}
    finally:
        execute("DELETE FROM games WHERE id = ?", (game,))
        execute("DELETE FROM systems WHERE id = ?", (sys_id,))
        execute("DELETE FROM emulators WHERE id = ?", (emu,))
