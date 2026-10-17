# =============================================================================
# PASS-59-59 — job-resume and commit-batching defects
# =============================================================================
# (a) RARefreshJob batched its commits every 25 games, so one game's
#     exception rolled back up to 24 earlier games that success_count had
#     already counted (silent data loss). ra_sync / platform_sync already
#     commit per game.
# (b) Every resumable game-walking job persisted `'current': i + 1` at the
#     TOP of iteration i, before item i ran. resume_from_params slices
#     `ids[current:]`, so the in-progress item was skipped on resume and
#     counted nowhere (Pass 49.8 named ra_sync + platform_sync ×2; the same
#     shape lived in ra_refresh and psn_refresh).
# (c) RASyncJob and SteamSyncJob resumed a snapshot with no user_id, and
#     every per-user upsert then hit `user_id NOT NULL` (migration 009).
#     psn_refresh and the Xbox path already refuse such a snapshot.
#
# Every job is driven against a throwaway sqlite DB under tmp_path: the
# module's `_get_conn`, the persist helpers and the singleton-lock helpers are
# all patched, so nothing reaches the real library DB or the network.
# =============================================================================

import sqlite3
import types

import pytest
import requests


TOTAL = 12          # persist fires at i == 10, so 2 items remain after it
CRASH_AT = 10       # index of the item in flight when the "crash" lands
USER_ID = 7


class _Crash(Exception):
    """Raised from persist_job_progress to simulate the process dying."""


class _NoWait:
    """Stand-in for shutdown_requested: never blocks, never signals."""

    def wait(self, *_a, **_kw):
        return False

    def is_set(self):
        return False


class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


def _make_db(path):
    conn = sqlite3.connect(str(path))
    conn.executescript("""
        CREATE TABLE systems (id INTEGER PRIMARY KEY, folder TEXT, name TEXT);
        CREATE TABLE games (
            id INTEGER PRIMARY KEY, title TEXT, rom_path TEXT, system_id INTEGER,
            ra_game_id TEXT, ra_achievement_count INTEGER,
            has_retroachievements INTEGER,
            steam_app_id TEXT, xbox_title_id TEXT
        );
        CREATE TABLE psn_games (id INTEGER PRIMARY KEY, title TEXT,
                                npwr_id TEXT, user_id INTEGER);
        CREATE TABLE user_settings (user_id INTEGER, psn_npsso TEXT);
        INSERT INTO systems VALUES (1, 'snes', 'Super Nintendo');
    """)
    for gid in range(1, TOTAL + 1):
        conn.execute(
            "INSERT INTO games (id, title, rom_path, system_id, ra_game_id, "
            "steam_app_id, xbox_title_id) VALUES (?, ?, ?, 1, ?, ?, ?)",
            (gid, f"G{gid}", f"snes/G{gid}.sfc", str(gid), str(gid), str(gid)),
        )
        conn.execute(
            "INSERT INTO psn_games (id, title, npwr_id, user_id) VALUES (?, ?, ?, ?)",
            (gid, f"G{gid}", f"NPWR{gid}", USER_ID),
        )
    conn.execute("INSERT INTO user_settings VALUES (?, 'npsso')", (USER_ID,))
    conn.commit()
    conn.close()


@pytest.fixture
def job_env(tmp_path, monkeypatch):
    """Patch one job module onto a tmp DB; record what each run processed."""
    db_path = tmp_path / 'jobs.db'
    _make_db(db_path)

    def _conn():
        c = sqlite3.connect(str(db_path), timeout=5)
        c.row_factory = sqlite3.Row
        return c

    state = {'processed': [], 'progress': None, 'params': None, 'crash': True}

    def _start(_kind, params):
        state['params'] = params
        return 'persist-id'

    def _progress(_pid, progress):
        if state['crash']:
            state['progress'] = dict(progress)
            raise _Crash()

    def patch_module(mod):
        monkeypatch.setattr(mod, '_get_conn', _conn)
        monkeypatch.setattr(mod, 'persist_job_start', _start)
        monkeypatch.setattr(mod, 'persist_job_progress', _progress)
        monkeypatch.setattr(mod, 'persist_job_complete', lambda *a, **kw: None)
        monkeypatch.setattr(mod, 'release_singleton_fd', lambda *a, **kw: None)
        monkeypatch.setattr(mod, 'acquire_job_singleton_lock', lambda *_a: 0)
        monkeypatch.setattr(mod, 'try_acquire_singleton_or_warn', lambda *_a, **_kw: 0)
        monkeypatch.setattr(mod, 'shutdown_requested', _NoWait())
        if hasattr(mod, '_get_ra_credentials'):
            monkeypatch.setattr(mod, '_get_ra_credentials', lambda: ('user', 'key'))

    return types.SimpleNamespace(
        db_path=db_path, conn=_conn, state=state, patch=patch_module,
        monkeypatch=monkeypatch,
    )


# ---------------------------------------------------------------------------
# Per-job drivers: patch the external call to record the item, start a fresh
# run synchronously, and name the resume entry point.
# ---------------------------------------------------------------------------


def _drive_ra_refresh(env):
    from services.jobs import ra_refresh as mod
    env.patch(mod)
    env.monkeypatch.setattr(requests, 'get', lambda *a, **kw: _Resp(200, []))

    def _match(title, _rom, _ra_games):
        env.state['processed'].append(title)
        return {'ID': 1, 'NumAchievements': 5}
    env.monkeypatch.setattr(mod, 'match_ra_game', _match)

    job = mod.RARefreshJob()
    job.running = True
    job._run_refresh()
    return mod.RARefreshJob


def _drive_ra_sync(env):
    from services.jobs import ra_sync as mod
    env.patch(mod)

    def _get(_url, params=None, **_kw):
        env.state['processed'].append(f"G{params['g']}")
        return _Resp(500, {})
    env.monkeypatch.setattr(requests, 'get', _get)

    job = mod.RASyncJob()
    job.system_id = 1
    job.system_name = 'Super Nintendo'
    job._user_id = USER_ID
    job.running = True
    job._run_sync()
    return mod.RASyncJob


def _drive_steam(env):
    from services.jobs import platform_sync as mod
    import scraper.scrape_steam as steam
    env.patch(mod)
    env.monkeypatch.setattr(mod, '_get_steam_credentials', lambda user_id=None: ('k', 's'))

    def _ach(_key, _sid, app_id):
        env.state['processed'].append(f"G{app_id}")
        return None
    env.monkeypatch.setattr(steam, 'get_player_achievements', _ach)

    job = mod.SteamSyncJob()
    job._user_id = USER_ID
    job.running = True
    job._run_sync()
    return mod.SteamSyncJob


def _drive_xbox(env):
    from services.jobs import platform_sync as mod
    import scraper.scrape_xbox as xbox
    env.patch(mod)
    env.monkeypatch.setattr(mod, '_get_xbox_credentials', lambda: ('a', 'b'))
    env.monkeypatch.setattr(
        xbox, 'get_authenticated_session',
        lambda *_a: {'auth_header': 'h', 'xuid': 'x'},
    )

    def _ach(_auth, _xuid, title_id):
        env.state['processed'].append(f"G{title_id}")
        return None
    env.monkeypatch.setattr(xbox, 'get_achievements', _ach)

    job = mod.XboxSyncJob()
    job.user_id = USER_ID
    job.running = True
    job._run_sync()
    return mod.XboxSyncJob


def _drive_psn(env):
    from services.jobs import psn_refresh as mod
    import routes.trophies as trophies
    env.patch(mod)

    titles = [types.SimpleNamespace(np_communication_id=f"NPWR{g}")
              for g in range(1, TOTAL + 1)]
    client = types.SimpleNamespace(trophy_titles=lambda: iter(titles))
    psnawp = types.SimpleNamespace(me=lambda: client)
    env.monkeypatch.setattr(trophies, 'create_psn_client', lambda *_a, **_kw: (psnawp, None))

    def _sync(self, _client, npwr_id, psn_game, _target, _conn):
        env.state['processed'].append(psn_game['title'])
        return 0
    env.monkeypatch.setattr(mod.PSNRefreshJob, '_sync_game_trophies', _sync)

    job = mod.PSNRefreshJob()
    job.npwr_ids = [f"NPWR{g}" for g in range(1, TOTAL + 1)]
    job._npsso = 'npsso'
    job._user_id = USER_ID
    job.running = True
    job._run_refresh()
    return mod.PSNRefreshJob


DRIVERS = {
    'ra_refresh': _drive_ra_refresh,
    'ra_sync': _drive_ra_sync,
    'steam_sync': _drive_steam,
    'xbox_sync': _drive_xbox,
    'psn_refresh': _drive_psn,
}


class TestResumeDoesNotSkipTheInFlightItem:
    """(b) + the Pass 49.8 re-check: crash at the persist tick of item
    CRASH_AT, resume from what was persisted, and every item must run
    exactly once with the counts adding up to the total."""

    @pytest.mark.parametrize('name', sorted(DRIVERS))
    def test_resume_processes_in_flight_item(self, job_env, name):
        job_cls = DRIVERS[name](job_env)
        state = job_env.state

        expected = [f"G{g}" for g in range(1, TOTAL + 1)]
        assert state['processed'] == expected[:CRASH_AT], \
            'first run should stop at the persist tick, before item CRASH_AT'
        progress = state['progress']
        assert progress is not None

        # Persisted `current` must equal the number of finished items.
        finished = progress['success'] + progress['failed'] + progress['skipped']
        assert progress['current'] == finished, (
            f"{name}: persisted current={progress['current']} but only "
            f"{finished} items had finished — resume would skip one"
        )

        # Round trip: resume and let it run to the end.
        state['processed'].clear()
        state['crash'] = False
        job = job_cls()
        assert job.resume_from_params(state['params'], progress) is True
        job._thread.join(timeout=10)
        assert not job._thread.is_alive()

        assert state['processed'] == expected[CRASH_AT:], (
            f"{name}: resume ran {state['processed']}, expected {expected[CRASH_AT:]}"
        )
        status = job.get_status()
        assert status['success'] + status['failed'] + status['skipped'] == TOTAL


class TestRARefreshCommitsPerGame:
    """(a) One game's exception must not roll back the games before it."""

    def test_failure_does_not_discard_earlier_games(self, job_env):
        from services.jobs import ra_refresh as mod
        job_env.patch(mod)
        job_env.monkeypatch.setattr(requests, 'get', lambda *a, **kw: _Resp(200, []))

        def _match(title, _rom, _ra_games):
            if title == 'G6':
                raise RuntimeError('boom')
            return {'ID': 100, 'NumAchievements': 5}
        job_env.monkeypatch.setattr(mod, 'match_ra_game', _match)

        conn = job_env.conn()
        conn.execute("DELETE FROM games WHERE id > 6")
        conn.commit()
        conn.close()

        job = mod.RARefreshJob()
        job.running = True
        job._run_refresh()

        status = job.get_status()
        assert status['success'] == 5 and status['failed'] == 1

        conn = job_env.conn()
        rows = conn.execute(
            "SELECT id, ra_game_id, has_retroachievements FROM games "
            "WHERE id <= 5 ORDER BY id"
        ).fetchall()
        conn.close()
        lost = [r['id'] for r in rows
                if r['has_retroachievements'] != 1 or r['ra_game_id'] != '100']
        assert lost == [], (
            f"games {lost} were counted as success but their writes were rolled back"
        )


class TestResumeRefusesSnapshotWithoutUserId:
    """(c) A pre-Pass-31 snapshot has no user_id; resuming it would fail
    every per-user upsert yet report `completed`. Refuse it, as psn_refresh
    and XboxSyncJob do."""

    @pytest.mark.parametrize('progress', [{'current': 3, 'success': 3,
                                           'failed': 0, 'skipped': 0}, None])
    @pytest.mark.parametrize('which', ['ra_sync', 'steam_sync'])
    def test_resume_without_user_id_is_refused(self, job_env, which, progress):
        if which == 'ra_sync':
            from services.jobs import ra_sync as mod
            job = mod.RASyncJob()
            worker = '_run_sync'
            params = {'system_id': 1, 'system_name': 'SNES', 'game_ids': [1, 2, 3, 4]}
        else:
            from services.jobs import platform_sync as mod
            job = mod.SteamSyncJob()
            worker = '_run_sync'
            params = {'game_ids': [1, 2, 3, 4]}
        job_env.patch(mod)

        ran = []
        setattr(job, worker, lambda: ran.append(True))

        assert not job.resume_from_params(params, progress), \
            f"{which} resumed a snapshot with no user_id"
        if job._thread is not None:
            job._thread.join(timeout=5)
        assert ran == [], f"{which} started its worker without a user_id"
