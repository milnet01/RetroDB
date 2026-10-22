"""PASS-59-81 — the player's cores: platform names, ranking, the installer,
the player's default rule, recommended settings and the routes' gates.

docs/specs/PASS-59-81-player-cores-and-settings.md. A fake HTTP layer
serves a small index and hand-built zips; no test reaches the network or
starts a real player. The profile lives under tmp_path.
"""
import io
import stat
import zipfile
import zlib
from itertools import count

import pytest

from services.database import execute, query

_seq = count()
PROBE = 'PlayerCoresProbe'


# -----------------------------------------------------------------------------
# The fake HTTP layer
# -----------------------------------------------------------------------------

class _Resp:
    def __init__(self, status=200, body=b'', headers=None):
        self.status_code = status
        self.content = body
        self.text = body.decode('utf-8', 'replace')
        self.headers = headers or {'Content-Length': str(len(body))}

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i:i + size]

    def close(self):
        pass


class FakeHTTP:
    def __init__(self):
        self.routes = {}
        self.calls = []

    def get(self, url, stream=False):
        self.calls.append(url)
        return self.routes.get(url, _Resp(404))

    def head(self, url):
        self.calls.append(url)
        r = self.routes.get(url, _Resp(404))
        return _Resp(r.status_code, b'', r.headers)


def _zip(members: dict) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as zf:
        for name, data in members.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _crc(data: bytes) -> str:
    return f'{zlib.crc32(data):08x}'


@pytest.fixture
def pc(tmp_path, monkeypatch):
    """player_cores with the profile under tmp_path, Linux x86_64, a fresh
    index cache and the fake HTTP layer installed."""
    from services import player_cores
    monkeypatch.setattr('config.BASE_DIR', str(tmp_path / 'base'))
    monkeypatch.setattr('platform_utils.IS_LINUX', True)
    monkeypatch.setattr('platform_utils.IS_WINDOWS', False)
    monkeypatch.setattr('platform_utils.IS_MACOS', False)
    monkeypatch.setattr('services.player_cores.platform.machine', lambda: 'x86_64')
    monkeypatch.setattr(player_cores, '_index_cache', {'dir': None, 'at': 0.0, 'data': None})
    http = FakeHTTP()
    monkeypatch.setattr(player_cores, '_http_get', http.get)
    monkeypatch.setattr(player_cores, '_http_head', http.head)
    player_cores.http = http
    return player_cores


BASE = 'https://buildbot.libretro.com/nightly/linux/x86_64/latest'


def _serve_index(pc, lines):
    pc.http.routes[f'{BASE}/.index-extended'] = _Resp(200, '\n'.join(lines).encode())


def _serve_core(pc, core, data=b'\x7fELF core', crc=None, member=None, index=True):
    name = f'{core}_libretro.so'
    pc.http.routes[f'{BASE}/{name}.zip'] = _Resp(200, _zip({member or name: data}))
    if index:
        _serve_index(pc, [f'2026-10-19 {crc or _crc(data)} {name}.zip'])


# -----------------------------------------------------------------------------
# INV-1 platform names, and the buildbot directory
# -----------------------------------------------------------------------------

@pytest.mark.parametrize('flags, expected', [
    ((True, False, False), 'snes9x_libretro.so'),
    ((False, True, False), 'snes9x_libretro.dll'),
    ((False, False, True), 'snes9x_libretro.dylib'),
])
def test_inv1_core_file_name(pc, monkeypatch, flags, expected):
    for name, value in zip(('IS_LINUX', 'IS_WINDOWS', 'IS_MACOS'), flags):
        monkeypatch.setattr(f'platform_utils.{name}', value)
    assert pc.core_file_name('snes9x') == expected


@pytest.mark.parametrize('flags, machine, expected', [
    ((True, False, False), 'x86_64', 'linux/x86_64'),
    ((True, False, False), 'aarch64', 'linux/aarch64'),
    ((False, True, False), 'AMD64', 'windows/x86_64'),
    ((False, False, True), 'x86_64', 'apple/osx/x86_64'),
    ((False, False, True), 'arm64', 'apple/osx/arm64'),
    ((True, False, False), 'riscv64', None),
    ((False, True, False), 'ARM64', None),
])
def test_buildbot_dir(pc, monkeypatch, flags, machine, expected):
    for name, value in zip(('IS_LINUX', 'IS_WINDOWS', 'IS_MACOS'), flags):
        monkeypatch.setattr(f'platform_utils.{name}', value)
    monkeypatch.setattr('services.player_cores.platform.machine', lambda: machine)
    assert pc.buildbot_dir() == expected


# -----------------------------------------------------------------------------
# INV-2 the automatic core is the first one the index lists
# -----------------------------------------------------------------------------

def test_inv2_ranking_skips_a_core_the_index_lacks(pc):
    _serve_index(pc, ['2026-10-19 0badf00d nestopia_libretro.so.zip',
                      '2026-10-19 0badf00d fceumm_libretro.so.zip'])
    assert pc.auto_core('nes') == 'nestopia'
    assert pc.auto_core('famicom') == 'nestopia'   # same_as


def test_inv2_empty_index_gives_no_core(pc):
    _serve_index(pc, [])
    assert pc.auto_core('nes') is None


def test_index_fetched_once_an_hour(pc):
    _serve_index(pc, ['2026-10-19 0badf00d mesen_libretro.so.zip'])
    pc.auto_core('nes')
    pc.auto_core('snes')
    assert pc.http.calls.count(f'{BASE}/.index-extended') == 1


def test_offline_index_falls_back_to_an_installed_core(pc):
    from services import player
    path = player.core_file('fceumm_libretro.so')
    path.parent.mkdir(parents=True)
    path.write_bytes(b'x')
    assert pc.index() is None                      # the fake answers 404
    assert pc.auto_core('nes') == 'fceumm'


# -----------------------------------------------------------------------------
# INV-3 a download URL holds only the host, the platform and a table core
# -----------------------------------------------------------------------------

@pytest.mark.parametrize('core', ['../x', 'notacore', 'snes9x/../../x', ''])
def test_inv3_unknown_core_makes_no_request(pc, core):
    with pytest.raises(pc.CoreInstallError):
        pc.install(core)
    assert pc.http.calls == []


# -----------------------------------------------------------------------------
# INV-4 a bad download leaves the existing core byte-identical
# -----------------------------------------------------------------------------

def _existing_core(pc):
    from services import player
    path = player.core_file('snes9x_libretro.so')
    path.parent.mkdir(parents=True)
    path.write_bytes(b'old core bytes')
    return path


def _no_leftovers(path):
    return [p.name for p in path.parent.iterdir() if p.name.startswith('.')] == []


def test_inv4_wrong_crc_installs_nothing(pc):
    path = _existing_core(pc)
    _serve_core(pc, 'snes9x', crc='deadbeef')
    with pytest.raises(pc.CoreInstallError, match='checksum'):
        pc.install('snes9x')
    assert path.read_bytes() == b'old core bytes'
    assert _no_leftovers(path)


def test_inv4_member_under_a_directory_is_not_extracted(pc):
    path = _existing_core(pc)
    _serve_core(pc, 'snes9x', member='evil/snes9x_libretro.so')
    with pytest.raises(pc.CoreInstallError, match='holds no'):
        pc.install('snes9x')
    assert path.read_bytes() == b'old core bytes'
    assert _no_leftovers(path)


def test_install_puts_the_core_in_place(pc):
    data = b'\x7fELF new core'
    _serve_core(pc, 'snes9x', data=data)
    dest = pc.install('snes9x')
    assert dest.read_bytes() == data
    assert dest.stat().st_mode & stat.S_IXUSR
    assert pc.installed() == {'snes9x': {'crc': _crc(data), 'date': '2026-10-19'}}
    assert _no_leftovers(dest)


def test_download_over_the_cap_fails(pc, monkeypatch):
    monkeypatch.setattr(pc, 'MAX_BYTES', 10)
    path = _existing_core(pc)
    _serve_core(pc, 'snes9x', data=b'x' * 4096)
    with pytest.raises(pc.CoreInstallError, match='256 MiB'):
        pc.install('snes9x')
    assert path.read_bytes() == b'old core bytes'
    assert _no_leftovers(path)


# -----------------------------------------------------------------------------
# INV-13 nothing installs from another host
# -----------------------------------------------------------------------------

def test_inv13_redirect_fails_the_install(pc):
    from services import player
    _serve_core(pc, 'snes9x')
    pc.http.routes[f'{BASE}/snes9x_libretro.so.zip'] = _Resp(
        302, b'', {'Location': 'http://example.invalid/'})
    with pytest.raises(pc.CoreInstallError, match='302'):
        pc.install('snes9x')
    assert not player.core_file('snes9x_libretro.so').exists()
    assert not any(u.startswith('http://example.invalid') for u in pc.http.calls)


def test_shader_pack_member_outside_the_folder_fails(pc):
    from services import player
    pc.http.routes[pc.SHADERS_URL] = _Resp(200, _zip({'../escape.slangp': b'x'}))
    with pytest.raises(pc.CoreInstallError, match='unsafe'):
        pc.install_shaders()
    assert not pc.shaders_ready()
    assert not (player.profile_dir().parent / 'escape.slangp').exists()


def test_shader_pack_installs(pc):
    pc.http.routes[pc.SHADERS_URL] = _Resp(200, _zip({'crt/crt-easymode.slangp': b'x'}))
    pc.install_shaders()
    assert (pc.shaders_dir() / 'crt' / 'crt-easymode.slangp').read_bytes() == b'x'


# -----------------------------------------------------------------------------
# DB-backed: a probe system, the player's row with a stub program
# -----------------------------------------------------------------------------

def _exe(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('#!/bin/sh\n')
    path.chmod(0o755)
    return path


@pytest.fixture
def world(pc, tmp_path, setup_complete, monkeypatch):
    """The player's row pointing at a stub program, and a factory for probe
    systems (each with one game) in table folders."""
    monkeypatch.setattr('services.launch_resolver._allowed_rom_roots', lambda: [])
    monkeypatch.setattr('services.player._user_system_dir', lambda: str(tmp_path / 'bios'))
    row = pc.player_row()
    if row is None:
        execute("INSERT INTO emulators (name, binary_name, args_template, is_retroarch, "
                "is_player, enabled) VALUES ('RetroDB Player', 'retrodb-player', 'x', 0, 1, 1)")
        row = pc.player_row()
    saved = (row['binary_path_override'], row['enabled'])
    execute("UPDATE emulators SET binary_path_override = ?, enabled = 1 WHERE id = ?",
            (str(_exe(tmp_path / 'retrodb-player')), row['id']))
    made = {'systems': [], 'emus': []}

    def system(folder, standalone=None):
        """A probe system in `folder` (renamed so the real one is left alone)
        with one game; `standalone` 'ok' or 'broken' adds a default emulator."""
        n = next(_seq)
        real = query("SELECT id, folder FROM systems WHERE folder = ?", (folder,), one=True)
        if real:
            execute("UPDATE systems SET folder = ? WHERE id = ?", (f'{folder}-moved{n}', real['id']))
            made.setdefault('moved', []).append((real['id'], folder))
        sid = execute("INSERT INTO systems (name, folder) VALUES (?, ?)", (f'{PROBE} {n}', folder))
        made['systems'].append(sid)
        if standalone:
            binary = tmp_path / f'emu{n}'
            if standalone == 'ok':
                _exe(binary)
            eid = execute("INSERT INTO emulators (name, binary_name, binary_path_override, "
                          "args_template, is_retroarch, enabled) VALUES (?, 'probe-emu', ?, "
                          "'\"{rom}\"', 0, 1)", (f'{PROBE} Emu {n}', str(binary)))
            made['emus'].append(eid)
            execute("INSERT INTO system_emulators (system_id, emulator_id, is_default) "
                    "VALUES (?, ?, 1)", (sid, eid))
        rom = tmp_path / f'rom{n}.bin'
        rom.write_bytes(b'x')
        games = [execute("INSERT INTO games (system_id, title, rom_path) VALUES (?, ?, ?)",
                         (sid, f'{PROBE} game {n}-{i}', str(tmp_path / f'rom{n}-{i}.bin')))
                 for i in range(2)]
        for i in range(2):
            (tmp_path / f'rom{n}-{i}.bin').write_bytes(b'x')
        return {'sid': sid, 'games': games, 'folder': folder}

    yield {'player': row['id'], 'system': system}
    execute("DELETE FROM emulator_setting_choices WHERE emulator_id = ?", (row['id'],))
    for sid in made['systems']:
        execute("DELETE FROM games WHERE system_id = ?", (sid,))
        execute("DELETE FROM system_emulators WHERE system_id = ?", (sid,))
        execute("DELETE FROM systems WHERE id = ?", (sid,))
    for eid in made['emus']:
        execute("DELETE FROM emulators WHERE id = ?", (eid,))
    for real_id, folder in made.get('moved', []):
        execute("UPDATE systems SET folder = ? WHERE id = ?", (folder, real_id))
    execute("UPDATE emulators SET binary_path_override = ?, enabled = ? WHERE id = ?",
            (*saved, row['id']))


def _default_emulator(sid):
    row = query("SELECT emulator_id FROM system_emulators WHERE system_id = ? AND is_default = 1",
                (sid,), one=True)
    return row['emulator_id'] if row else None


# -----------------------------------------------------------------------------
# INV-5 the player becomes default only where no default resolves
# -----------------------------------------------------------------------------

def test_inv5_default_only_where_none_resolves(world):
    a = world['system']('snes', standalone='ok')
    b = world['system']('nes')
    c = world['system']('gba', standalone='broken')
    before = _default_emulator(a['sid'])
    for s, core in ((a, 'snes9x'), (b, 'mesen'), (c, 'mgba')):
        from services import player_cores
        player_cores.map_system(s['sid'], core)
    assert _default_emulator(a['sid']) == before
    assert _default_emulator(b['sid']) == world['player']
    assert _default_emulator(c['sid']) == world['player']
    row = query("SELECT retroarch_core, is_default FROM system_emulators "
                "WHERE system_id = ? AND emulator_id = ?", (a['sid'], world['player']), one=True)
    assert dict(row) == {'retroarch_core': 'snes9x_libretro.so', 'is_default': 0}


# -----------------------------------------------------------------------------
# INV-8 game choice > system choice > table default, in the right file
# -----------------------------------------------------------------------------

def _install_fake(pc, core):
    from services import player
    path = player.core_file(pc.core_file_name(core))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b'x')


def _choose(player_id, scope, scope_id, setting, value):
    from services import standalone_settings
    standalone_settings.set_choice(player_id, scope, scope_id, setting, value)


def _resolve(game_id):
    from services.launch_resolver import resolve_launch_context
    return resolve_launch_context(game_id)


def test_inv8_choice_order_and_file(pc, world):
    from services import player
    s = world['system']('nes')
    _serve_index(pc, ['2026-10-19 0badf00d mesen_libretro.so.zip'])
    _install_fake(pc, 'mesen')
    _choose(world['player'], 'system', s['sid'], 'latency', 'off')
    _choose(world['player'], 'game', s['games'][0], 'latency', '1')
    _resolve(s['games'][0])
    _resolve(s['games'][1])
    system_cfg = player._read(pc.system_cfg_path('nes'))
    assert system_cfg['run_ahead_enabled'] == 'false'
    assert system_cfg['aspect_ratio_index'] == '22'
    assert player._read(player._game_file(s['games'][0], 'cfg'))['run_ahead_enabled'] == 'true'
    assert 'run_ahead_enabled' not in player._read(player._game_file(s['games'][1], 'cfg'))


def test_shader_left_out_until_the_pack_is_on_disk(pc, world):
    from services import player
    s = world['system']('nes')
    _serve_index(pc, ['2026-10-19 0badf00d mesen_libretro.so.zip'])
    _install_fake(pc, 'mesen')
    _choose(world['player'], 'game', s['games'][0], 'shader', 'crt')
    _resolve(s['games'][0])
    assert 'video_shader' not in player._read(player._game_file(s['games'][0], 'cfg'))
    (pc.shaders_dir() / 'crt').mkdir(parents=True)
    _resolve(s['games'][0])
    cfg = player._read(player._game_file(s['games'][0], 'cfg'))
    assert cfg['video_shader'] == str(pc.shaders_dir() / 'crt' / 'crt-easymode.slangp')


# -----------------------------------------------------------------------------
# INV-10 a key set in the player's menu stays until a RetroDB choice is saved
# -----------------------------------------------------------------------------

def _client(admin_test_client, role):
    return admin_test_client(user={'id': 900, 'username': f'{role}-stub', 'role': role})


def test_inv10_user_key_kept_until_a_panel_choice(pc, world, admin_test_client):
    import json
    from services import player
    s = world['system']('nes')
    gid = s['games'][0]
    _serve_index(pc, ['2026-10-19 0badf00d mesen_libretro.so.zip'])
    _install_fake(pc, 'mesen')
    rec = player._game_file(gid, 'json')
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({'user': {'cfg': {'aspect_ratio_index': '0'}, 'opt': {}},
                               'written': {'cfg': {}, 'opt': {}}}))
    _resolve(gid)
    assert player._read(player._game_file(gid, 'cfg'))['aspect_ratio_index'] == '0'
    client, csrf = _client(admin_test_client, 'editor')
    rv = client.put(f'/api/games/{gid}/emulator-settings', json={'aspect_ratio': 'core'},
                    headers={'X-CSRF-Token': csrf})
    assert rv.status_code == 200, rv.get_data(as_text=True)[:300]
    _resolve(gid)
    assert player._read(player._game_file(gid, 'cfg'))['aspect_ratio_index'] == '22'
    assert 'aspect_ratio_index' not in player._record(gid)['user']['cfg']


# -----------------------------------------------------------------------------
# INV-9's PUT half, and the settings view the player serves
# -----------------------------------------------------------------------------

def test_inv9_core_choice_outside_the_list_refused(pc, world, admin_test_client):
    s = world['system']('snes')
    _serve_index(pc, ['2026-10-19 0badf00d snes9x_libretro.so.zip'])
    client, csrf = _client(admin_test_client, 'editor')
    url = f"/api/games/{s['games'][0]}/emulator-settings"
    assert client.put(url, json={'core': 'mame'}, headers={'X-CSRF-Token': csrf}).status_code == 400
    rv = client.put(url, json={'core': 'bsnes'}, headers={'X-CSRF-Token': csrf})
    assert rv.status_code == 200, rv.get_data(as_text=True)[:300]
    view = rv.get_json()['data']
    assert view['emulator']['id'] == world['player']
    core = next(x for x in view['settings'] if x['setting'] == 'core')
    assert core['value'] == 'bsnes' and core['values'] == ['snes9x', 'bsnes']


# -----------------------------------------------------------------------------
# INV-11 the routes' permission gates
# -----------------------------------------------------------------------------

def test_inv11_install_and_update_need_manage_settings(pc, world, admin_test_client, monkeypatch):
    from services.jobs import player_cores_job
    started = []
    monkeypatch.setattr(player_cores_job, 'request', lambda *a, **k: started.append(a) or 'j')
    client, csrf = _client(admin_test_client, 'editor')
    for route in ('install', 'update'):
        rv = client.post(f'/api/player/cores/{route}', headers={'X-CSRF-Token': csrf})
        assert rv.status_code == 403
    assert started == []


def test_inv11_viewer_cannot_put_a_choice(pc, world, admin_test_client):
    s = world['system']('snes')
    client, csrf = _client(admin_test_client, 'viewer')
    rv = client.put(f"/api/games/{s['games'][0]}/emulator-settings", json={'core': 'bsnes'},
                    headers={'X-CSRF-Token': csrf})
    assert rv.status_code == 403
    assert query("SELECT 1 FROM emulator_setting_choices WHERE emulator_id = ?",
                 (world['player'],)) == []


def test_every_table_folder_is_a_known_system():
    """The table is keyed by systems.folder; a folder no library uses (the
    spec's draft said superfamicom, libraries say sfc) is never matched."""
    import json
    import config
    from services.player_cores import TABLE_PATH
    with open(TABLE_PATH, encoding='utf-8') as f:
        table = json.load(f)
    unknown = sorted(k for k in table if not k.startswith('_') and k not in config.SYSTEM_NAME_MAP)
    assert not unknown, f"folders not in config.SYSTEM_NAME_MAP: {unknown}"
