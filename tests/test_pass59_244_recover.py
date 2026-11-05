"""PASS-59-244: updates and game launches recover from a failure."""
import json

import updater_apply
from tests.test_updater import fake_install  # noqa: F401  (a fixture)


def _status(plan):
    with open(plan['status_path']) as f:
        return json.load(f)


def test_an_unknown_plan_restarts_the_old_version(fake_install):  # noqa: F811
    """The old app has already exited when the helper reads the plan."""
    _install, _tree, plan, _db = fake_install
    plan['plan_version'] = 99
    assert updater_apply.apply(plan) == 2
    assert updater_apply.healthy_version(plan['port']) == '1.0.0'


def test_a_folder_error_before_the_swap_restarts_the_old_version(fake_install, tmp_path):  # noqa: F811
    install, _tree, plan, _db = fake_install
    blocker = tmp_path / 'not-a-folder'
    blocker.write_text('x')
    plan['rollback_dir'] = str(blocker / 'rollback')   # cannot be made
    assert updater_apply.apply(plan) == 1
    assert _status(plan)['result'] == 'failed'
    assert (install / 'VERSION').read_text() == '1.0.0'
    assert updater_apply.healthy_version(plan['port']) == '1.0.0'


def test_a_plan_missing_a_key_restarts_the_old_version(fake_install):  # noqa: F811
    _install, _tree, plan, _db = fake_install
    del plan['rollback_dir']
    assert updater_apply.apply(plan) == 1
    assert updater_apply.healthy_version(plan['port']) == '1.0.0'


def test_a_launch_checks_and_starts_under_one_lock(admin_test_client, monkeypatch):
    """Two launches at once both passed the one-session check."""
    from routes import launch

    class Launcher:
        def active(self):
            held.append(launch._launch_lock.locked())
            return []
    held = []
    monkeypatch.setattr(launch, 'get_launcher', lambda: Launcher())
    monkeypatch.setattr(launch, 'has_permission', lambda p: True)
    monkeypatch.setattr(launch, 'resolve_launch_context',
                        lambda gid: (_ for _ in ()).throw(launch.LaunchResolutionError('stop')))
    client, csrf = admin_test_client()
    client.post('/api/game/1/launch', headers={'X-CSRF-Token': csrf})
    assert held == [True]


# --- Cheats: the launch copy is taken back from this launch's core only ---

import os  # noqa: E402
from pathlib import Path  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture
def cheat_profile(tmp_path, monkeypatch):
    from services import player, player_cores
    monkeypatch.setattr(player, 'profile_dir', lambda: tmp_path)
    monkeypatch.setattr(player_cores, 'library_name',
                        lambda core: {'snes9x': 'Snes9x', 'mgba': 'mGBA'}.get(core))
    own = player._game_file(5, 'cht')
    own.parent.mkdir(parents=True)
    own.write_text('cheats = 1\n')
    return tmp_path, own


def test_take_back_reads_only_this_launchs_copy(cheat_profile):
    from services import cheats
    profile, own = cheat_profile
    rom = Path('/roms/snes/Mario.sfc')
    cheats.place_for_launch(5, 'snes9x', rom, profile)
    mine = profile / 'cheats' / 'Snes9x' / 'Mario.cht'
    mine.write_text('cheats = 1\ncheat0_enable = true\n')
    other = profile / 'cheats' / 'mGBA' / 'Mario.cht'       # another game's leftover
    other.parent.mkdir(parents=True)
    other.write_text('cheats = 9\n')
    os.utime(other, (mine.stat().st_mtime + 60,) * 2)       # and newer
    cheats.take_back(5, rom, profile)
    assert own.read_text() == 'cheats = 1\ncheat0_enable = true\n'
    assert not mine.exists() and other.exists()


def test_a_cheat_error_of_any_kind_never_stops_a_launch(cheat_profile, monkeypatch):
    from services import cheats, player_cores
    profile, _own = cheat_profile

    def bad(core):
        raise ValueError('odd core name')
    monkeypatch.setattr(player_cores, 'library_name', bad)
    cheats.place_for_launch(5, 'snes9x', Path('/roms/snes/Mario.sfc'), profile)
    monkeypatch.setattr(cheats, '_copy', lambda *a: (_ for _ in ()).throw(KeyError('x')))
    cheats.take_back(5, Path('/roms/snes/Mario.sfc'), profile)


# --- An emulator's settings file is written safely ----------------------------------

def test_writing_settings_keeps_a_symlink_and_the_files_mode(tmp_path):
    from services import standalone_settings as ss
    real = tmp_path / 'real.ini'
    real.write_text('a = 1\n')
    real.chmod(0o644)
    link = tmp_path / 'settings.ini'
    link.symlink_to(real)
    ss.write_lines(link, ['a = 2\n'])
    assert link.is_symlink()
    assert real.read_text() == 'a = 2\n'
    assert real.stat().st_mode & 0o777 == 0o644


def test_a_failed_settings_write_leaves_no_temp_file(tmp_path, monkeypatch):
    from services import standalone_settings as ss
    target = tmp_path / 'settings.ini'
    target.write_text('a = 1\n')
    monkeypatch.setattr(os, 'replace', lambda *a: (_ for _ in ()).throw(OSError('disk full')))
    with pytest.raises(OSError):
        ss.write_lines(target, ['a = 2\n'])
    assert sorted(p.name for p in tmp_path.iterdir()) == ['settings.ini']


def test_a_settings_file_that_is_not_utf8_round_trips(tmp_path):
    from services import standalone_settings as ss
    target = tmp_path / 'settings.ini'
    target.write_bytes(b'name = Caf\xe9\n')
    lines = ss._read_lines(target)
    ss.write_lines(target, lines)
    assert target.read_bytes() == b'name = Caf\xe9\n'


def test_the_pack_index_is_written_in_one_step(monkeypatch, tmp_path):
    """sources.json was written in place; a crash left it half-written."""
    from services import cheats
    written = []
    monkeypatch.setattr('services.atomic_io.atomic_write_text',
                        lambda path, text, **k: written.append(str(path)))
    monkeypatch.setattr(cheats, 'store_dir', lambda: tmp_path)
    cheats._save_pack_sources({'x': {'files': 1}})
    assert written == [str(tmp_path / 'sources.json')]


# --- game-launch.js: the core wait ends, and the dialog is RetroDB's own ----------

import shutil  # noqa: E402
import subprocess  # noqa: E402

from tests._util import REPO_ROOT  # noqa: E402

NODE = shutil.which('node')

_LAUNCH = r"""
const vm = require('vm'); const fs = require('fs');
// Anything the play screen touches: every property and call answers with
// another stub, so only the launch flow's own logic is under test.
function stub() {
  const f = function () { return stub(); };
  return new Proxy(f, {get: (t, k) => k === 'then' ? undefined
                          : k === Symbol.toPrimitive ? (() => '') : stub(),
                        set: () => true});
}
const said = []; let launches = 0;
const MODE = process.argv[1];
const coreStatus = MODE === 'error-page'
    ? {status: 500, ok: false, json: async () => { throw new Error('html'); }}
    : {status: 200, ok: true, json: async () => ({data: {running: true, current_item: 'snes9x'}})};
const ctx = {console, Promise, JSON, Date, Math,
  setTimeout: (f) => { setImmediate(f); return 1; }, clearTimeout(){}, setInterval: () => 1,
  clearInterval(){}, addEventListener(){}, removeEventListener(){},
  document: stub(),
  t: (s, v) => s, escapeHtml: (s) => s, formatBytes: (n) => String(n),
  showNotification: (m, kind) => said.push(kind), showConfirm: (a, b, yes, no) => no(),
  fetch: async (url) => url.includes('/launch')
      ? (launches++, {status: 202, ok: true,
                      json: async () => ({installing: {core: 'snes9x', system: 'SNES'}})})
      : coreStatus,
};
ctx.window = ctx; vm.createContext(ctx);
vm.runInContext(fs.readFileSync('static/js/game-launch.js', 'utf8'), ctx);
const btn = new Proxy({dataset: {gameId: '1'}, innerHTML: '', title: '', disabled: false,
                       classList: {contains: () => true}},
                      {get: (t, k) => k in t ? t[k] : stub()});
ctx.launchGame(btn).then(() => console.log(JSON.stringify({said, launches})));
"""


@pytest.mark.skipif(NODE is None, reason='node not available')
@pytest.mark.parametrize('mode', ['error-page', 'never-done'])
def test_the_core_wait_gives_up(mode):
    """It read an error page as "the download is done" and sent the launch
    again, and it waited forever on a download that never ended."""
    try:
        res = subprocess.run([NODE, '-e', _LAUNCH, mode], cwd=REPO_ROOT, capture_output=True,
                             text=True, timeout=30)
    except subprocess.TimeoutExpired:
        pytest.fail('the core wait never ended')
    assert res.returncode == 0, res.stderr[-800:]
    out = json.loads(res.stdout.strip().splitlines()[-1])
    assert out['launches'] == 1 and out['said'][-1] == 'error'


def test_the_launch_asks_with_retrodbs_own_dialog():
    src = (REPO_ROOT / 'static/js/game-launch.js').read_text() if hasattr(REPO_ROOT, 'joinpath') \
        else open(os.path.join(REPO_ROOT, 'static/js/game-launch.js')).read()
    assert 'confirm(' not in src.replace('showConfirm(', '')
