"""PASS-59-240: sign-ins and keys stay out of logs, backups and shared files."""

import sqlite3

import config


SECRET = 'S3cretPassw0rdValue'


def test_saved_job_error_is_redacted():
    """job_queue.error_message keeps the error, never a credential in a URL."""
    from services.jobs.base import persist_job_complete, persist_job_start
    job_id = persist_job_start('ra_sync')
    persist_job_complete(job_id, status='failed',
                         error=f'HTTPError for https://x.test/api?sspassword={SECRET}&g=1')
    conn = sqlite3.connect(config.DB_PATH)
    try:
        (saved,) = conn.execute('SELECT error_message FROM job_queue WHERE id = ?',
                                (job_id,)).fetchone()
    finally:
        conn.close()
    assert SECRET not in saved
    assert 'HTTPError' in saved


def test_psn_refresh_error_is_hidden_from_other_users(admin_test_client, monkeypatch):
    """Another member's refresh error may name their sign-in; only its owner sees it."""
    from services.jobs import psn_refresh_job
    client, _csrf = admin_test_client()
    monkeypatch.setattr(psn_refresh_job, '_user_id', 999, raising=False)
    monkeypatch.setattr(psn_refresh_job, 'error_message', 'PSN authentication failed: boom')
    body = client.get('/api/psn/bulk-refresh/status').get_json()
    assert body['error'] is None


def test_psn_refresh_error_still_reaches_its_owner(admin_test_client, monkeypatch):
    from services.jobs import psn_refresh_job
    client, _csrf = admin_test_client()
    monkeypatch.setattr(psn_refresh_job, '_user_id', 1, raising=False)
    monkeypatch.setattr(psn_refresh_job, 'error_message', 'PSN authentication failed: boom')
    body = client.get('/api/psn/bulk-refresh/status').get_json()
    assert body['error'] == 'PSN authentication failed: boom'


def _make_user(name):
    conn = sqlite3.connect(config.DB_PATH)
    try:
        cur = conn.execute("INSERT INTO users (username, password_hash, role, is_active) "
                           "VALUES (?, 'x', 'viewer', 1)", (name,))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def test_deleting_a_user_signs_them_out_of_the_emulators(admin_test_client, monkeypatch):
    """Their RA token must leave DuckStation's and PCSX2's files with them."""
    signed_out = []
    monkeypatch.setattr('services.ra_sign_in.sign_out', signed_out.append)
    client, csrf = admin_test_client()
    uid = _make_user('pass59240-delete')
    r = client.post(f'/api/users/{uid}/delete', headers={'X-CSRF-Token': csrf})
    assert r.status_code == 200, r.get_json()
    assert signed_out == [uid]


def test_deactivating_a_user_signs_them_out_of_the_emulators(admin_test_client, monkeypatch):
    signed_out = []
    monkeypatch.setattr('services.ra_sign_in.sign_out', signed_out.append)
    client, csrf = admin_test_client()
    uid = _make_user('pass59240-deactivate')
    r = client.post(f'/api/users/{uid}/update', json={'is_active': False},
                    headers={'X-CSRF-Token': csrf})
    assert r.status_code == 200, r.get_json()
    assert signed_out == [uid]


def _small_db(path):
    conn = sqlite3.connect(path)
    conn.execute('CREATE TABLE t (x)')
    conn.execute("INSERT INTO t VALUES ('live')")
    conn.commit()
    conn.close()


def test_backup_is_private_while_it_is_written(tmp_path, monkeypatch):
    """A backup holds password hashes and tokens: never readable by others,
    not even for the moment before it is finished."""
    import os
    from services import database
    src = tmp_path / 'live.db'
    _small_db(src)
    out = tmp_path / 'backups'
    out.mkdir()
    modes = {}
    real_connect = sqlite3.connect

    class _Src:
        def __init__(self, conn):
            self._c = conn

        def backup(self, dst, *a, **k):
            self._c.backup(dst, *a, **k)
            for f in out.iterdir():
                modes[f.name] = f.stat().st_mode & 0o777

        def __getattr__(self, name):
            return getattr(self._c, name)

    def _connect(path, *a, **k):
        conn = real_connect(path, *a, **k)
        return _Src(conn) if str(path) == str(src) else conn

    monkeypatch.setattr(database.sqlite3, 'connect', _connect)
    old = os.umask(0o022)
    try:
        database.backup_database(str(src), str(out / 'b.db'))
    finally:
        os.umask(old)
    assert modes, 'the backup was never observed mid-write'
    assert all(m & 0o077 == 0 for m in modes.values()), modes
    assert (out / 'b.db').stat().st_mode & 0o077 == 0


def test_failed_backup_keeps_the_previous_one(tmp_path, monkeypatch):
    from services import database
    src = tmp_path / 'live.db'
    _small_db(src)
    dst = tmp_path / 'b.db'
    _small_db(dst)
    previous = dst.read_bytes()

    real_connect = sqlite3.connect

    class _BadVerify:
        def execute(self, sql, *a):
            class _R:
                def fetchone(self):
                    return ('corrupt',) if 'integrity_check' in sql else None
            return _R()

        def close(self):
            pass

    calls = []

    def _connect(path, *a, **k):
        calls.append(str(path))
        # src, then the write target, then the verify open
        if len(calls) == 3:
            return _BadVerify()
        return real_connect(path, *a, **k)

    monkeypatch.setattr(database.sqlite3, 'connect', _connect)
    import pytest
    with pytest.raises(RuntimeError):
        database.backup_database(str(src), str(dst))
    assert dst.read_bytes() == previous
    assert sorted(p.name for p in tmp_path.iterdir()) == ['b.db', 'live.db']
